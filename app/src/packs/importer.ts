import type { Db } from '../db/types';
import { joinPath, type FileStore } from '../storage/files';
import type { SvgSanitizer } from './sanitize';
import { validatePack, type PackFiles } from './validate';
import { PackZipError, readPackZip } from './zip';

export const PACKS_DIR = 'packs';

export type ImportSource = 'manual' | 'github';

export type ImportOutcome =
  | {
      status: 'imported' | 'updated';
      packId: string;
      version: number;
      title: string;
      added: number;
      updated: number;
      unchanged: number;
      removed: number;
      warnings: string[];
    }
  | { status: 'already-installed'; packId: string; version: number; title: string; warnings: string[] }
  | { status: 'rejected'; reason: string; errors: string[]; warnings: string[] };

export interface ImportDeps {
  db: Db;
  files: FileStore;
  sanitizeSvg: SvgSanitizer;
  now?: () => number;
}

interface ReelRow {
  id: string;
  pack_id: string;
  revision: number;
}

const decoder = new TextDecoder();
const encoder = new TextEncoder();

export function packDir(packId: string, version: number): string {
  return joinPath(PACKS_DIR, packId, `v${version}`);
}

export async function importPackZip(zip: Uint8Array, deps: ImportDeps, source: ImportSource = 'manual'): Promise<ImportOutcome> {
  let files: PackFiles;
  try {
    files = readPackZip(zip);
  } catch (e) {
    const msg = e instanceof PackZipError ? e.message : String(e);
    return { status: 'rejected', reason: 'invalid-zip', errors: [msg], warnings: [] };
  }
  return importPackFiles(files, deps, source);
}

export async function importPackFiles(files: PackFiles, deps: ImportDeps, source: ImportSource): Promise<ImportOutcome> {
  const { db, files: store } = deps;
  const now = deps.now ?? Date.now;

  const report = validatePack(files);
  if (!report.ok || !report.pack) {
    return { status: 'rejected', reason: 'invalid-pack', errors: report.errors, warnings: report.warnings };
  }
  const pack = report.pack;
  const packId: string = pack.id;
  const version: number = pack.version;
  const title: string = pack.title;

  const existing = (await db.all<{ version: number }>('SELECT version FROM packs WHERE id = ?', [packId]))[0];
  if (existing && existing.version === version) {
    return { status: 'already-installed', packId, version, title, warnings: report.warnings };
  }
  if (existing && existing.version > version) {
    return {
      status: 'rejected',
      reason: 'older-version',
      errors: [`pack '${packId}' v${version} is older than the installed v${existing.version}`],
      warnings: report.warnings,
    };
  }

  // 1) write the files (SVGs sanitized). Nothing references this folder until the database step
  //    below commits, so a partial folder from an interrupted import is harmless and replaced here.
  const finalDir = packDir(packId, version);
  await store.remove(finalDir);
  try {
    for (const [path, data] of files) {
      let out = data;
      if (path.toLowerCase().endsWith('.svg')) out = encoder.encode(deps.sanitizeSvg(decoder.decode(data)));
      await store.write(joinPath(finalDir, path), out);
    }
  } catch (e) {
    await store.remove(finalDir);
    throw e;
  }

  // 2) register in the database (scheduling of existing reels is kept)
  const reelIds: string[] = pack.reels;
  let added = 0;
  let updated = 0;
  let unchanged = 0;
  let removed = 0;
  try {
    await db.transaction(async (tx) => {
      const ts = now();
      await tx.run(
        `INSERT INTO packs (id, version, title, language, path, source, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET version = excluded.version, title = excluded.title, language = excluded.language,
           path = excluded.path, source = excluded.source, imported_at = excluded.imported_at`,
        [packId, version, title, pack.language, finalDir, source, ts],
      );

      const before = await tx.all<ReelRow>('SELECT id, pack_id, revision FROM reels WHERE pack_id = ? AND removed = 0', [packId]);
      for (const [index, reelId] of reelIds.entries()) {
        const reel = report.reels.get(reelId);
        const prev = (await tx.all<ReelRow>('SELECT id, pack_id, revision FROM reels WHERE id = ?', [reelId]))[0];
        const params = [reel.revision, reel.title, JSON.stringify(reel.tags), reel.duration, joinPath(finalDir, 'reels', reelId), index, ts];
        if (!prev) {
          await tx.run(
            `INSERT INTO reels (revision, title, tags, duration, path, order_index, updated_at, id, pack_id, removed)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
            [...params, reelId, packId],
          );
          await tx.run('INSERT INTO cards (reel_id, created_at) VALUES (?, ?)', [reelId, ts]);
          added += 1;
        } else {
          await tx.run(
            `UPDATE reels SET revision = ?, title = ?, tags = ?, duration = ?, path = ?, order_index = ?, updated_at = ?,
               pack_id = ?, removed = 0 WHERE id = ?`,
            [...params, packId, reelId],
          );
          if (reel.revision !== prev.revision) updated += 1;
          else unchanged += 1;
        }
      }

      const keep = new Set(reelIds);
      for (const old of before.filter((r) => !keep.has(r.id))) {
        await tx.run('UPDATE reels SET removed = 1, updated_at = ? WHERE id = ?', [ts, old.id]);
        removed += 1;
      }
    });
  } catch (e) {
    await store.remove(finalDir);
    throw e;
  }

  // 3) old versions of this pack are no longer referenced
  for (const name of await store.list(joinPath(PACKS_DIR, packId))) {
    if (name !== `v${version}`) await store.remove(joinPath(PACKS_DIR, packId, name));
  }

  return {
    status: existing ? 'updated' : 'imported',
    packId,
    version,
    title,
    added,
    updated,
    unchanged,
    removed,
    warnings: report.warnings,
  };
}

export interface InstalledPack {
  id: string;
  version: number;
  title: string;
  source: ImportSource;
  imported_at: number;
  reels: number;
}

export async function listInstalledPacks(db: Db): Promise<InstalledPack[]> {
  return db.all<InstalledPack>(
    `SELECT p.id, p.version, p.title, p.source, p.imported_at,
            (SELECT COUNT(*) FROM reels r WHERE r.pack_id = p.id AND r.removed = 0) AS reels
     FROM packs p ORDER BY p.imported_at DESC`,
  );
}
