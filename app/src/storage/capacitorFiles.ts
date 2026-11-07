import { Directory, Encoding, Filesystem } from '@capacitor/filesystem';
import { fromBase64, toBase64 } from './base64';
import { assertSafePath, type FileStore } from './files';

const DIR = Directory.Data;

/** Device implementation: files under the app's private data directory. */
export class CapacitorFileStore implements FileStore {
  async write(path: string, data: Uint8Array | string): Promise<void> {
    assertSafePath(path);
    if (typeof data === 'string') {
      await Filesystem.writeFile({ path, directory: DIR, data, encoding: Encoding.UTF8, recursive: true });
    } else {
      await Filesystem.writeFile({ path, directory: DIR, data: toBase64(data), recursive: true });
    }
  }

  async read(path: string): Promise<Uint8Array> {
    const res = await Filesystem.readFile({ path, directory: DIR });
    if (typeof res.data !== 'string') return new Uint8Array(await res.data.arrayBuffer());
    return fromBase64(res.data);
  }

  async readText(path: string): Promise<string> {
    const res = await Filesystem.readFile({ path, directory: DIR, encoding: Encoding.UTF8 });
    return typeof res.data === 'string' ? res.data : await res.data.text();
  }

  async exists(path: string): Promise<boolean> {
    try {
      await Filesystem.stat({ path, directory: DIR });
      return true;
    } catch {
      return false;
    }
  }

  async remove(path: string): Promise<void> {
    let type: string;
    try {
      type = (await Filesystem.stat({ path, directory: DIR })).type;
    } catch {
      return;
    }
    if (type === 'directory') await Filesystem.rmdir({ path, directory: DIR, recursive: true });
    else await Filesystem.deleteFile({ path, directory: DIR });
  }

  async list(dir: string): Promise<string[]> {
    try {
      const res = await Filesystem.readdir({ path: dir, directory: DIR });
      return res.files.map((f) => f.name).sort();
    } catch {
      return [];
    }
  }
}
