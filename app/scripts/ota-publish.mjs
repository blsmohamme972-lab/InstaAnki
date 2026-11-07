#!/usr/bin/env node
/**
 * Prepares an OTA release of the web bundle.
 *
 *   node scripts/ota-publish.mjs --dist dist --out ota-out [--notes "..."] \
 *        (--key-file key.pem | --key-env OTA_SIGNING_KEY) [--verify-with public.pem]
 *
 * Output (uploaded as assets of the "ota-channel" GitHub Release):
 *   latest.json      bundleVersion, minShellVersion, notes, files[{path, sha256, size}]
 *   latest.json.sig  Base64 DER ECDSA-P256/SHA-256 signature of the exact bytes of latest.json
 *   <sha256>         every file of the bundle, named by its hash (content-addressed)
 */
import { createHash, createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
import { copyFileSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { parseArgs } from 'node:util';

const SAFE_SEGMENT = /^[A-Za-z0-9._@+-]+$/;

export function listFiles(dir) {
  const out = [];
  const walk = (d) => {
    for (const name of readdirSync(d).sort()) {
      const p = join(d, name);
      if (statSync(p).isDirectory()) walk(p);
      else out.push(relative(dir, p).split('\\').join('/'));
    }
  };
  walk(dir);
  return out;
}

export function buildManifest(dist, { notes = '', releasedAt = new Date().toISOString() } = {}) {
  const info = JSON.parse(readFileSync(join(dist, 'bundle-info.json'), 'utf8'));
  if (!/^\d+\.\d+\.\d+$/.test(info.bundleVersion)) throw new Error(`bad bundleVersion ${info.bundleVersion}`);
  const files = listFiles(dist).map((path) => {
    if (!path.split('/').every((s) => SAFE_SEGMENT.test(s))) throw new Error(`unsafe file name in bundle: ${path}`);
    const data = readFileSync(join(dist, path));
    return { path, sha256: createHash('sha256').update(data).digest('hex'), size: data.length };
  });
  if (!files.some((f) => f.path === 'index.html')) throw new Error('dist has no index.html');
  return {
    bundleVersion: info.bundleVersion,
    minShellVersion: info.minShellVersion,
    releasedAt,
    notes,
    files,
  };
}

export function signBytes(bytes, privateKeyPem) {
  return sign('sha256', bytes, createPrivateKey(privateKeyPem)).toString('base64');
}

export function verifyBytes(bytes, signatureB64, publicKeyPem) {
  return verify('sha256', bytes, createPublicKey(publicKeyPem), Buffer.from(signatureB64.trim(), 'base64'));
}

export function publish({ dist, out, notes, privateKeyPem, verifyWithPem }) {
  const manifest = buildManifest(dist, { notes });
  const json = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  const sig = signBytes(json, privateKeyPem);
  if (verifyWithPem && !verifyBytes(json, sig, verifyWithPem)) {
    throw new Error('signature does not verify with the public key embedded in the app (wrong OTA_SIGNING_KEY?)');
  }
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'latest.json'), json);
  writeFileSync(join(out, 'latest.json.sig'), `${sig}\n`);
  for (const f of manifest.files) copyFileSync(join(dist, f.path), join(out, f.sha256));
  return manifest;
}

function main() {
  const { values } = parseArgs({
    options: {
      dist: { type: 'string', default: 'dist' },
      out: { type: 'string', default: 'ota-out' },
      notes: { type: 'string', default: '' },
      'key-file': { type: 'string' },
      'key-env': { type: 'string' },
      'verify-with': { type: 'string' },
    },
  });
  const privateKeyPem = values['key-file']
    ? readFileSync(values['key-file'], 'utf8')
    : values['key-env']
      ? process.env[values['key-env']]
      : undefined;
  if (!privateKeyPem) throw new Error('missing signing key (--key-file or --key-env)');
  const manifest = publish({
    dist: values.dist,
    out: values.out,
    notes: values.notes,
    privateKeyPem,
    verifyWithPem: values['verify-with'] ? readFileSync(values['verify-with'], 'utf8') : undefined,
  });
  const total = manifest.files.reduce((n, f) => n + f.size, 0);
  console.log(`bundle ${manifest.bundleVersion} (minShell ${manifest.minShellVersion}): ${manifest.files.length} files, ${(total / 1024).toFixed(0)} KB`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    main();
  } catch (e) {
    console.error(`ota-publish: ${e.message}`);
    process.exit(1);
  }
}
