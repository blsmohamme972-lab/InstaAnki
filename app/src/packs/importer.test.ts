import { JSDOM } from 'jsdom';
import initSqlJs, { type SqlJsStatic } from 'sql.js';
import { zipSync } from 'fflate';
import { beforeAll, describe, expect, it } from 'vitest';
import { migrate } from '../db/migrate';
import { MIGRATIONS } from '../db/migrations';
import { openSqlJs } from '../db/sqljs';
import type { Db } from '../db/types';
import { MemoryFileStore } from '../storage/files';
import { importPackZip, listInstalledPacks } from './importer';
import { createSvgSanitizer } from './sanitize';
import { editJson, editText, loadDir, reelPath, SAMPLE_PACK_DIR, SAMPLE_REEL, zipFiles } from './testkit';
import { readPackZip } from './zip';

let SQL: SqlJsStatic;
const sanitizeSvg = createSvgSanitizer(new JSDOM('').window as unknown as Window);

beforeAll(async () => {
  SQL = await initSqlJs();
});

async function setup(): Promise<{ db: Db; files: MemoryFileStore }> {
  const db = openSqlJs(SQL);
  await migrate(db, MIGRATIONS);
  return { db, files: new MemoryFileStore() };
}

function sampleZip(mutate?: (f: Map<string, Uint8Array>) => void): Uint8Array {
  const files = loadDir(SAMPLE_PACK_DIR);
  mutate?.(files);
  return zipFiles(files);
}

const bump = (version: number, revision?: number) => (f: Map<string, Uint8Array>) => {
  editJson(f, 'pack.json', (p) => (p.version = version));
  if (revision !== undefined) editJson(f, reelPath('reel.json'), (r) => (r.revision = revision));
};

describe('readPackZip', () => {
  it('accepts pack.json at the root or inside one top-level folder', () => {
    const files = loadDir(SAMPLE_PACK_DIR);
    expect(readPackZip(zipFiles(files)).has('pack.json')).toBe(true);
    const nested = readPackZip(zipFiles(files, 'cardio-basics-001-v1/'));
    expect(nested.has('pack.json')).toBe(true);
    expect(nested.has(reelPath('reel.json'))).toBe(true);
  });

  it('rejects path traversal entries', () => {
    const zip = zipSync({ 'pack.json': new Uint8Array([123, 125]), '../evil.sh': new Uint8Array([1]) });
    expect(() => readPackZip(zip)).toThrow(/unsafe entry path: \.\.\/evil\.sh/);
  });

  it('rejects zips over the limits', () => {
    const zip = zipFiles(loadDir(SAMPLE_PACK_DIR));
    expect(() => readPackZip(zip, { maxEntries: 2, maxTotalBytes: 1e9 })).toThrow(/too large/);
    expect(() => readPackZip(zip, { maxEntries: 100, maxTotalBytes: 1000 })).toThrow(/too large/);
  });

  it('rejects non-zip data and zips without pack.json', () => {
    expect(() => readPackZip(new Uint8Array([1, 2, 3, 4]))).toThrow(/not a valid zip/);
    expect(() => readPackZip(zipSync({ 'a/x.txt': new Uint8Array([1]), 'b/y.txt': new Uint8Array([2]) }))).toThrow(/pack.json not found/);
  });

  it('ignores macOS metadata', () => {
    const files = loadDir(SAMPLE_PACK_DIR);
    files.set('__MACOSX/._pack.json', new Uint8Array([0]));
    files.set('.DS_Store', new Uint8Array([0]));
    const out = readPackZip(zipFiles(files));
    expect([...out.keys()].some((k) => k.includes('MACOSX') || k.includes('DS_Store'))).toBe(false);
  });
});

describe('importPackZip', () => {
  it('imports the example pack: files, reel and a new card', async () => {
    const { db, files } = await setup();
    const res = await importPackZip(sampleZip(), { db, files, sanitizeSvg, now: () => 1000 });
    expect(res).toMatchObject({ status: 'imported', packId: 'cardio-basics-001', version: 1, added: 1, removed: 0 });

    const base = `packs/cardio-basics-001/v1/reels/${SAMPLE_REEL}`;
    expect(await files.exists(`${base}/audio.opus`)).toBe(true);
    expect(await files.list('packs/cardio-basics-001')).toEqual(['v1']);
    const svg = await files.readText(`${base}/img/heart.svg`);
    expect(svg).toContain('id="left-ventricle"');
    expect(svg).toContain('xmlns="http://www.w3.org/2000/svg"');

    expect(await db.all('SELECT id, revision, path, removed FROM reels')).toEqual([
      { id: SAMPLE_REEL, revision: 1, path: base, removed: 0 },
    ]);
    expect(await db.all('SELECT reel_id, state FROM cards')).toEqual([{ reel_id: SAMPLE_REEL, state: 'new' }]);
    expect(await listInstalledPacks(db)).toMatchObject([{ id: 'cardio-basics-001', version: 1, reels: 1, source: 'manual' }]);
  });

  it('is idempotent for the same version', async () => {
    const { db, files } = await setup();
    await importPackZip(sampleZip(), { db, files, sanitizeSvg });
    const again = await importPackZip(sampleZip(), { db, files, sanitizeSvg });
    expect(again.status).toBe('already-installed');
    expect(await db.all('SELECT COUNT(*) AS n FROM cards')).toEqual([{ n: 1 }]);
  });

  it('updates a pack, keeps scheduling, and deletes the old version folder', async () => {
    const { db, files } = await setup();
    await importPackZip(sampleZip(), { db, files, sanitizeSvg });
    await db.run("UPDATE cards SET state = 'review', reps = 4, liked = 1 WHERE reel_id = ?", [SAMPLE_REEL]);

    const res = await importPackZip(sampleZip(bump(2, 2)), { db, files, sanitizeSvg });
    expect(res).toMatchObject({ status: 'updated', version: 2, added: 0, updated: 1, unchanged: 0 });
    expect(await db.all('SELECT state, reps, liked FROM cards')).toEqual([{ state: 'review', reps: 4, liked: 1 }]);
    expect(await db.all('SELECT revision, path FROM reels')).toEqual([
      { revision: 2, path: `packs/cardio-basics-001/v2/reels/${SAMPLE_REEL}` },
    ]);
    expect(await files.list('packs/cardio-basics-001')).toEqual(['v2']);
  });

  it('marks reels dropped from a newer version as removed but keeps their history', async () => {
    const { db, files } = await setup();
    await importPackZip(sampleZip(), { db, files, sanitizeSvg });
    // v2 replaces the reel with a renamed copy
    const res = await importPackZip(
      sampleZip((f) => {
        bump(2)(f);
        for (const [k, v] of [...f]) {
          if (k.startsWith(`reels/${SAMPLE_REEL}/`)) {
            f.delete(k);
            f.set(k.replace(SAMPLE_REEL, 'cardio-heart-chambers-002'), v);
          }
        }
        editJson(f, 'pack.json', (p) => (p.reels = ['cardio-heart-chambers-002']));
        editJson(f, 'reels/cardio-heart-chambers-002/reel.json', (r) => (r.id = 'cardio-heart-chambers-002'));
      }),
      { db, files, sanitizeSvg },
    );
    expect(res).toMatchObject({ status: 'updated', added: 1, removed: 1 });
    expect(await db.all('SELECT id, removed FROM reels ORDER BY id')).toEqual([
      { id: SAMPLE_REEL, removed: 1 },
      { id: 'cardio-heart-chambers-002', removed: 0 },
    ]);
    expect(await db.all('SELECT COUNT(*) AS n FROM cards')).toEqual([{ n: 2 }]);
  });

  it('refuses an older version than the installed one', async () => {
    const { db, files } = await setup();
    await importPackZip(sampleZip(bump(3)), { db, files, sanitizeSvg });
    const res = await importPackZip(sampleZip(bump(2)), { db, files, sanitizeSvg });
    expect(res).toMatchObject({ status: 'rejected', reason: 'older-version' });
  });

  it('rejects invalid packs without writing anything', async () => {
    const { db, files } = await setup();
    const res = await importPackZip(
      sampleZip((f) => editText(f, reelPath('img/heart.svg'), (s) => s.replace('</svg>', '<script>alert(1)</script></svg>'))),
      { db, files, sanitizeSvg },
    );
    expect(res.status).toBe('rejected');
    expect(res.status === 'rejected' && res.errors.join('\n')).toMatch(/unsafe SVG/);
    expect(files.files.size).toBe(0);
    expect(await db.all('SELECT * FROM packs')).toEqual([]);
  });

  it('rejects broken zips', async () => {
    const { db, files } = await setup();
    const res = await importPackZip(new Uint8Array([80, 75, 3, 4, 0]), { db, files, sanitizeSvg });
    expect(res).toMatchObject({ status: 'rejected', reason: 'invalid-zip' });
  });

  it('cleans up the new folder if the database step fails', async () => {
    const { db, files } = await setup();
    await db.exec('DROP TABLE cards');
    await expect(importPackZip(sampleZip(), { db, files, sanitizeSvg })).rejects.toThrow();
    expect(await files.list('packs/cardio-basics-001')).toEqual([]);
    expect(await db.all('SELECT * FROM packs')).toEqual([]);
  });
});

describe('createSvgSanitizer', () => {
  it('strips scripts, handlers and foreignObject but keeps ids and shapes', () => {
    const dirty =
      '<svg viewBox="0 0 10 10" onload="alert(1)"><script>alert(2)</script><foreignObject><div>x</div></foreignObject>' +
      '<g id="lv"><rect x="1" y="1" width="2" height="2" onclick="alert(3)"/></g></svg>';
    const clean = sanitizeSvg(dirty);
    expect(clean).not.toMatch(/script|onload|onclick|foreignObject|alert/i);
    expect(clean).toContain('id="lv"');
    expect(clean).toContain('<rect');
  });
});
