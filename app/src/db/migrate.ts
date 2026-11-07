import type { Migration } from './migrations';
import type { Db } from './types';

export class DbNewerThanAppError extends Error {
  constructor(
    readonly dbVersion: number,
    readonly appVersion: number,
  ) {
    super(`database schema v${dbVersion} is newer than this app version (v${appVersion})`);
    this.name = 'DbNewerThanAppError';
  }
}

const VERSION_TABLE = `CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER NOT NULL,
  applied_at INTEGER NOT NULL
)`;

export async function getSchemaVersion(db: Db): Promise<number> {
  await db.exec(VERSION_TABLE);
  const rows = await db.all<{ v: number | null }>('SELECT MAX(version) AS v FROM schema_version');
  return rows[0]?.v ?? 0;
}

export interface MigrateOptions {
  /** Called once before the first pending migration, only for an existing (non-empty) database. */
  backup?: (fromVersion: number) => Promise<void>;
  /** Stop at this version (used when rebuilding an older schema during a restore). */
  target?: number;
  now?: () => number;
}

export interface MigrateResult {
  from: number;
  to: number;
  applied: number[];
}

export async function migrate(db: Db, migrations: Migration[], opts: MigrateOptions = {}): Promise<MigrateResult> {
  assertOrdered(migrations);
  const now = opts.now ?? Date.now;
  const latest = migrations.at(-1)?.version ?? 0;
  const target = opts.target ?? latest;
  const from = await getSchemaVersion(db);

  if (from > latest) throw new DbNewerThanAppError(from, latest);

  const pending = migrations.filter((m) => m.version > from && m.version <= target);
  if (pending.length === 0) return { from, to: from, applied: [] };

  if (from > 0 && opts.backup) await opts.backup(from);

  for (const m of pending) {
    await db.transaction(async (tx) => {
      await tx.exec(m.sql);
      await tx.run('INSERT INTO schema_version (version, applied_at) VALUES (?, ?)', [m.version, now()]);
    });
  }
  return { from, to: pending.at(-1)!.version, applied: pending.map((m) => m.version) };
}

function assertOrdered(migrations: Migration[]): void {
  migrations.forEach((m, i) => {
    if (m.version !== i + 1) throw new Error(`migration #${i} has version ${m.version}, expected ${i + 1}`);
  });
}
