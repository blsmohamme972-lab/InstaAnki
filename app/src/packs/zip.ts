import { unzipSync } from 'fflate';
import type { PackFiles } from './validate';

export class PackZipError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PackZipError';
  }
}

export interface ZipLimits {
  maxEntries: number;
  maxTotalBytes: number;
}

export const DEFAULT_ZIP_LIMITS: ZipLimits = { maxEntries: 5000, maxTotalBytes: 300 * 1024 * 1024 };

function isUnsafe(name: string): boolean {
  return name.startsWith('/') || name.includes('\\') || /^[A-Za-z]:/.test(name) || name.split('/').includes('..');
}

/**
 * Extracts a pack zip into memory with zip-slip and zip-bomb guards. pack.json may sit at the zip
 * root or inside one top-level folder; returned paths are relative to the pack root.
 */
export function readPackZip(bytes: Uint8Array, limits: ZipLimits = DEFAULT_ZIP_LIMITS): PackFiles {
  let unsafe: string | null = null;
  let tooBig = false;
  let entries = 0;
  let total = 0;

  let raw: Record<string, Uint8Array>;
  try {
    raw = unzipSync(bytes, {
      filter(file) {
        const name = file.name;
        if (name.endsWith('/')) return false;
        if (name.startsWith('__MACOSX/') || name.split('/').at(-1) === '.DS_Store') return false;
        if (isUnsafe(name)) {
          unsafe ??= name;
          return false;
        }
        entries += 1;
        total += file.originalSize;
        if (entries > limits.maxEntries || total > limits.maxTotalBytes) {
          tooBig = true;
          return false;
        }
        return true;
      },
    });
  } catch (e) {
    throw new PackZipError(`not a valid zip: ${(e as Error).message}`);
  }
  if (unsafe) throw new PackZipError(`unsafe entry path: ${unsafe}`);
  if (tooBig) throw new PackZipError(`zip is too large (limit ${limits.maxEntries} files / ${Math.round(limits.maxTotalBytes / 1048576)} MB)`);

  let prefix = '';
  if (!('pack.json' in raw)) {
    const tops = new Set(Object.keys(raw).map((k) => k.split('/')[0]!));
    const only = tops.size === 1 ? [...tops][0]! : null;
    if (only && `${only}/pack.json` in raw) prefix = `${only}/`;
    else throw new PackZipError('pack.json not found at the zip root (or inside a single top-level folder)');
  }

  const files: PackFiles = new Map();
  for (const [name, data] of Object.entries(raw)) {
    if (name.startsWith(prefix)) files.set(name.slice(prefix.length), data);
  }
  return files;
}
