import { Directory, Encoding, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { createBackup, parseBackup, restoreBackup, saveBackup } from '../db/backup';
import { getSchemaVersion } from '../db/migrate';
import { MIGRATIONS } from '../db/migrations';
import type { Db } from '../db/types';
import { importPackZip, type ImportOutcome, type ImportSource } from '../packs/importer';
import { createSvgSanitizer } from '../packs/sanitize';
import { isNative, Shell, type IncomingFile, type ShellInfo } from '../platform/shell';
import { fromBase64 } from '../storage/base64';
import { MemoryFileStore, type FileStore } from '../storage/files';
import { bootDatabase, type BootDbResult } from './boot';

export interface Runtime {
  db: Db;
  files: FileStore;
  shell: ShellInfo;
  boot: BootDbResult;
}

async function openDb(): Promise<Db> {
  if (isNative()) {
    const { openCapacitorDb } = await import('../db/capacitor');
    return openCapacitorDb();
  }
  // Browser (development): in-memory sql.js, nothing is persisted.
  const [{ default: initSqlJs }, { default: wasmUrl }, { openSqlJs }] = await Promise.all([
    import('sql.js'),
    import('sql.js/dist/sql-wasm.wasm?url'),
    import('../db/sqljs'),
  ]);
  return openSqlJs(await initSqlJs({ locateFile: () => wasmUrl }));
}

async function openFiles(): Promise<FileStore> {
  if (!isNative()) return new MemoryFileStore();
  const { CapacitorFileStore } = await import('../storage/capacitorFiles');
  return new CapacitorFileStore();
}

export async function startRuntime(): Promise<Runtime> {
  const shell = await Shell.getInfo();
  const [db, files] = await Promise.all([openDb(), openFiles()]);
  const boot = await bootDatabase(db, files, MIGRATIONS, {
    bundleVersion: shell.bundleVersion,
    rolledBackFrom: shell.rolledBackFrom,
  });
  return { db, files, shell, boot };
}

const sanitizeSvg = createSvgSanitizer(window);

export function importZip(rt: Runtime, bytes: Uint8Array, source: ImportSource): Promise<ImportOutcome> {
  return importPackZip(bytes, { db: rt.db, files: rt.files, sanitizeSvg }, source);
}

/** Imports a zip that was shared to the app, then deletes it from the cache. */
export async function importIncoming(rt: Runtime, file: IncomingFile): Promise<ImportOutcome> {
  try {
    const res = await Filesystem.readFile({ path: file.path, directory: Directory.Cache });
    const bytes = typeof res.data === 'string' ? fromBase64(res.data) : new Uint8Array(await res.data.arrayBuffer());
    return await importZip(rt, bytes, 'manual');
  } finally {
    await Filesystem.deleteFile({ path: file.path, directory: Directory.Cache }).catch(() => undefined);
  }
}

export async function exportBackup(rt: Runtime): Promise<void> {
  const backup = await createBackup(rt.db, 'manual', rt.shell.bundleVersion);
  const name = `instaanki-backup-${backup.createdAt.slice(0, 10)}.json`;
  const json = JSON.stringify(backup);
  if (!isNative()) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
    return;
  }
  const written = await Filesystem.writeFile({
    path: `exports/${name}`,
    directory: Directory.Cache,
    data: json,
    encoding: Encoding.UTF8,
    recursive: true,
  });
  await Share.share({ title: 'InstaAnki backup', files: [written.uri] });
}

/** Restores a backup file; the current data is saved first as a "manual" backup. */
export async function restoreFromFile(rt: Runtime, text: string): Promise<void> {
  const backup = parseBackup(text);
  await saveBackup(rt.files, await createBackup(rt.db, 'manual', rt.shell.bundleVersion));
  await restoreBackup(rt.db, backup, MIGRATIONS);
  await bootDatabase(rt.db, rt.files, MIGRATIONS, { bundleVersion: rt.shell.bundleVersion, rolledBackFrom: null });
}

export const schemaVersion = (rt: Runtime) => getSchemaVersion(rt.db);
