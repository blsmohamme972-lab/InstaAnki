/** Test helpers (node only): load the example pack from disk, mutate it, zip it. */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { zipSync } from 'fflate';
import type { PackFiles } from './validate';

export const SAMPLE_PACK_DIR = new URL('../../../examples/sample-pack/', import.meta.url).pathname;
export const SAMPLE_REEL = 'cardio-heart-chambers-001';

export function loadDir(dir: string): PackFiles {
  const files: PackFiles = new Map();
  const walk = (d: string) => {
    for (const name of readdirSync(d)) {
      const p = join(d, name);
      if (statSync(p).isDirectory()) walk(p);
      else files.set(relative(dir, p).split('\\').join('/'), new Uint8Array(readFileSync(p)));
    }
  };
  walk(dir);
  return files;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

export function getJson(files: PackFiles, path: string): any {
  return JSON.parse(dec.decode(files.get(path)!));
}

export function setJson(files: PackFiles, path: string, value: unknown): void {
  files.set(path, enc.encode(JSON.stringify(value, null, 2)));
}

export function editJson(files: PackFiles, path: string, fn: (v: any) => void): void {
  const v = getJson(files, path);
  fn(v);
  setJson(files, path, v);
}

export function editText(files: PackFiles, path: string, fn: (s: string) => string): void {
  files.set(path, enc.encode(fn(dec.decode(files.get(path)!))));
}

export function reelPath(file: string): string {
  return `reels/${SAMPLE_REEL}/${file}`;
}

export function zipFiles(files: PackFiles, prefix = ''): Uint8Array {
  const obj: Record<string, Uint8Array> = {};
  for (const [k, v] of files) obj[prefix + k] = v;
  return zipSync(obj);
}
