/**
 * App-private file storage. Paths are relative ("packs/x/v1/pack.json"), always with forward slashes.
 * Device: Capacitor Filesystem (Directory.Data). Web/tests: in memory.
 */
export interface FileStore {
  write(path: string, data: Uint8Array | string): Promise<void>;
  read(path: string): Promise<Uint8Array>;
  readText(path: string): Promise<string>;
  exists(path: string): Promise<boolean>;
  /** Removes a file or a whole directory (recursive). Missing paths are ignored. */
  remove(path: string): Promise<void>;
  /** Names of the direct children of a directory ([] if it does not exist). */
  list(dir: string): Promise<string[]>;
}

export function assertSafePath(path: string): void {
  if (
    path === '' ||
    path.startsWith('/') ||
    path.includes('\\') ||
    path.split('/').some((p) => p === '..' || p === '.' || p === '')
  ) {
    throw new Error(`unsafe path: ${JSON.stringify(path)}`);
  }
}

export function joinPath(...parts: string[]): string {
  return parts.filter((p) => p !== '').join('/');
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** In-memory implementation for the browser (dev) and unit tests. */
export class MemoryFileStore implements FileStore {
  readonly files = new Map<string, Uint8Array>();

  async write(path: string, data: Uint8Array | string): Promise<void> {
    assertSafePath(path);
    this.files.set(path, typeof data === 'string' ? encoder.encode(data) : data.slice());
  }

  async read(path: string): Promise<Uint8Array> {
    const data = this.files.get(path);
    if (!data) throw new Error(`file not found: ${path}`);
    return data;
  }

  async readText(path: string): Promise<string> {
    return decoder.decode(await this.read(path));
  }

  async exists(path: string): Promise<boolean> {
    return this.files.has(path) || [...this.files.keys()].some((k) => k.startsWith(`${path}/`));
  }

  async remove(path: string): Promise<void> {
    for (const key of [...this.files.keys()]) {
      if (key === path || key.startsWith(`${path}/`)) this.files.delete(key);
    }
  }

  async list(dir: string): Promise<string[]> {
    const prefix = dir === '' ? '' : `${dir}/`;
    const names = new Set<string>();
    for (const key of this.files.keys()) {
      if (key.startsWith(prefix)) names.add(key.slice(prefix.length).split('/')[0]!);
    }
    return [...names].sort();
  }
}
