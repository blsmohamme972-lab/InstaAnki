import type { FileStore } from '../storage/files';
import { getSchemaVersion, migrate } from './migrate';
import type { Migration } from './migrations';
import type { Db, Row } from './types';

export const BACKUP_DIR = 'backups';
export const KEEP_PRE_MIGRATION = 3;

export type BackupReason = 'pre-migration' | 'weekly' | 'manual';

export interface DbBackup {
  format: 'instaanki-db-backup';
  formatVersion: 1;
  schemaVersion: number;
  createdAt: string;
  reason: BackupReason;
  bundleVersion: string;
  tables: Record<string, Row[]>;
}

async function userTables(db: Db): Promise<string[]> {
  const rows = await db.all<{ name: string }>(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
  );
  return rows.map((r) => r.name);
}

/** Snapshot of every table as JSON. Portable across drivers and readable by humans. */
export async function createBackup(db: Db, reason: BackupReason, bundleVersion: string, now = new Date()): Promise<DbBackup> {
  return db.transaction(async (tx) => {
    const tables: Record<string, Row[]> = {};
    for (const name of await userTables(tx)) {
      tables[name] = await tx.all(`SELECT * FROM "${name}"`);
    }
    return {
      format: 'instaanki-db-backup',
      formatVersion: 1,
      schemaVersion: await getSchemaVersion(tx),
      createdAt: now.toISOString(),
      reason,
      bundleVersion,
      tables,
    };
  });
}

export function parseBackup(text: string): DbBackup {
  const data = JSON.parse(text) as Partial<DbBackup>;
  if (data.format !== 'instaanki-db-backup' || data.formatVersion !== 1 || typeof data.schemaVersion !== 'number' || typeof data.tables !== 'object' || data.tables === null) {
    throw new Error('not an InstaAnki backup file');
  }
  return data as DbBackup;
}

/**
 * Replaces the whole database with the backup: drops every table, rebuilds the schema at the
 * backup's version, then inserts the rows. Later migrations run on the next normal startup.
 */
export async function restoreBackup(db: Db, backup: DbBackup, migrations: Migration[]): Promise<void> {
  const latest = migrations.at(-1)?.version ?? 0;
  if (backup.schemaVersion > latest) {
    throw new Error(`backup schema v${backup.schemaVersion} is newer than this app (v${latest})`);
  }
  // One transaction: if anything fails, the current database stays untouched.
  await db.transaction(async (tx) => {
    for (const name of await userTables(tx)) await tx.exec(`DROP TABLE "${name}"`);
    await migrate(tx, migrations, { target: backup.schemaVersion });
    await tx.exec('DELETE FROM schema_version');
    const known = new Set(await userTables(tx));
    for (const [table, rows] of Object.entries(backup.tables)) {
      if (!known.has(table)) throw new Error(`backup contains unknown table "${table}"`);
      for (const row of rows) {
        const cols = Object.keys(row);
        if (cols.length === 0) continue;
        const sql = `INSERT INTO "${table}" (${cols.map((c) => `"${c}"`).join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`;
        await tx.run(sql, cols.map((c) => row[c] ?? null));
      }
    }
    const restored = await getSchemaVersion(tx);
    if (restored !== backup.schemaVersion) {
      throw new Error(`backup is inconsistent: schema_version says v${restored}, header says v${backup.schemaVersion}`);
    }
  });
}

function backupFileName(b: DbBackup): string {
  return `${b.createdAt.replace(/[:.]/g, '-')}_${b.reason}_v${b.schemaVersion}.json`;
}

export async function saveBackup(files: FileStore, backup: DbBackup): Promise<string> {
  const path = `${BACKUP_DIR}/${backupFileName(backup)}`;
  await files.write(path, JSON.stringify(backup));
  await pruneBackups(files, backup.reason, backup.reason === 'pre-migration' ? KEEP_PRE_MIGRATION : 4);
  return path;
}

export interface BackupEntry {
  name: string;
  reason: BackupReason;
  schemaVersion: number;
}

export async function listBackups(files: FileStore): Promise<BackupEntry[]> {
  const entries: BackupEntry[] = [];
  for (const name of await files.list(BACKUP_DIR)) {
    const m = /^.+_(pre-migration|weekly|manual)_v(\d+)\.json$/.exec(name);
    if (m) entries.push({ name, reason: m[1] as BackupReason, schemaVersion: Number(m[2]) });
  }
  return entries.sort((a, b) => a.name.localeCompare(b.name)); // oldest first (ISO timestamps)
}

async function pruneBackups(files: FileStore, reason: BackupReason, keep: number): Promise<void> {
  const same = (await listBackups(files)).filter((e) => e.reason === reason);
  for (const old of same.slice(0, Math.max(0, same.length - keep))) {
    await files.remove(`${BACKUP_DIR}/${old.name}`);
  }
}

/** Most recent pre-migration backup taken at exactly this schema version (used after a bundle rollback). */
export async function findPreMigrationBackup(files: FileStore, schemaVersion: number): Promise<DbBackup | null> {
  const match = (await listBackups(files)).filter((e) => e.reason === 'pre-migration' && e.schemaVersion === schemaVersion).at(-1);
  return match ? parseBackup(await files.readText(`${BACKUP_DIR}/${match.name}`)) : null;
}
