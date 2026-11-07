import { createBackup, findPreMigrationBackup, restoreBackup, saveBackup } from '../db/backup';
import { DbNewerThanAppError, migrate } from '../db/migrate';
import type { Migration } from '../db/migrations';
import type { Db } from '../db/types';
import type { FileStore } from '../storage/files';

export interface BootDbResult {
  schemaVersion: number;
  migratedFrom: number;
  /** True when the database was put back to the pre-migration backup after a bundle rollback. */
  restoredAfterRollback: boolean;
}

/**
 * Brings the database to this bundle's schema:
 *  - existing database + pending migrations -> pre-migration backup, then migrate
 *  - database newer than this bundle (the shell rolled back a broken update) -> restore the
 *    backup taken just before that update's migration, then continue normally
 */
export async function bootDatabase(
  db: Db,
  files: FileStore,
  migrations: Migration[],
  opts: { bundleVersion: string; rolledBackFrom: string | null },
): Promise<BootDbResult> {
  const backup = async () => {
    await saveBackup(files, await createBackup(db, 'pre-migration', opts.bundleVersion));
  };
  try {
    const res = await migrate(db, migrations, { backup });
    return { schemaVersion: res.to, migratedFrom: res.from, restoredAfterRollback: false };
  } catch (err) {
    if (!(err instanceof DbNewerThanAppError) || !opts.rolledBackFrom) throw err;
    const snapshot = await findPreMigrationBackup(files, err.appVersion);
    if (!snapshot) throw err;
    await restoreBackup(db, snapshot, migrations);
    const res = await migrate(db, migrations, { backup });
    return { schemaVersion: res.to, migratedFrom: err.dbVersion, restoredAfterRollback: true };
  }
}
