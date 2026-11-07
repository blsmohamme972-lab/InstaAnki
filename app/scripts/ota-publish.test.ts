import { generateKeyPairSync } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
// @ts-expect-error plain ESM script without type declarations
import { buildManifest, publish, verifyBytes } from './ota-publish.mjs';

const dirs: string[] = [];
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), 'ota-'));
  dirs.push(d);
  return d;
}
afterEach(() => dirs.splice(0).forEach((d) => rmSync(d, { recursive: true, force: true })));

function fakeDist(version = '0.2.0'): string {
  const dist = tmp();
  mkdirSync(join(dist, 'assets'));
  writeFileSync(join(dist, 'index.html'), '<html></html>');
  writeFileSync(join(dist, 'assets', 'index-AbC_1.js'), 'console.log(1)');
  writeFileSync(join(dist, 'assets', 'copy.js'), 'console.log(1)'); // same content -> same hash
  writeFileSync(join(dist, 'bundle-info.json'), JSON.stringify({ bundleVersion: version, minShellVersion: 1 }));
  return dist;
}

const keys = () => {
  const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  return {
    priv: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
    pub: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
  };
};

describe('ota-publish', () => {
  it('builds a manifest of every file with hashes', () => {
    const m = buildManifest(fakeDist(), { notes: 'n', releasedAt: 'x' });
    expect(m.bundleVersion).toBe('0.2.0');
    expect(m.files.map((f: { path: string }) => f.path)).toEqual(['assets/copy.js', 'assets/index-AbC_1.js', 'bundle-info.json', 'index.html']);
    expect(m.files[0].sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(m.files[0].sha256).toBe(m.files[1].sha256);
  });

  it('writes a signed manifest and content-addressed files', () => {
    const { priv, pub } = keys();
    const out = tmp();
    const m = publish({ dist: fakeDist(), out, notes: 'ملاحظات', privateKeyPem: priv, verifyWithPem: pub });
    const json = readFileSync(join(out, 'latest.json'));
    const sig = readFileSync(join(out, 'latest.json.sig'), 'utf8');
    expect(verifyBytes(json, sig, pub)).toBe(true);
    expect(JSON.parse(json.toString()).notes).toBe('ملاحظات');
    for (const f of m.files) expect(readFileSync(join(out, f.sha256)).length).toBe(f.size);
  });

  it('refuses to publish with a key that does not match the app', () => {
    const a = keys();
    const b = keys();
    expect(() => publish({ dist: fakeDist(), out: tmp(), notes: '', privateKeyPem: a.priv, verifyWithPem: b.pub })).toThrow(/does not verify/);
  });

  it('rejects bad versions and missing index.html', () => {
    expect(() => buildManifest(fakeDist('1.2'))).toThrow(/bad bundleVersion/);
    const dist = fakeDist();
    rmSync(join(dist, 'index.html'));
    expect(() => buildManifest(dist)).toThrow(/no index.html/);
  });
});
