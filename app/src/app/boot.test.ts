import initSqlJs, { type SqlJsStatic } from 'sql.js';
import { beforeAll, describe, expect, it } from 'vitest';
import { listBackups } from '../db/backup';
import { DbNewerThanAppError, getSchemaVersion, migrate } from '../db/migrate';
import { MIGRATIONS, type Migration } from '../db/migrations';
import { openSqlJs } from '../db/sqljs';
import { MemoryFileStore } from '../storage/files';
import { bootDatabase } from './boot';

let SQL: SqlJsStatic;
beforeAll(async () => {
  SQL = await initSqlJs();
});

const V2: Migration = { version: 2, name: 'v2', sql: 'CREATE TABLE extra (a INTEGER);' };
const opts = { bundleVersion: '0.1.0', rolledBackFrom: null };

describe('bootDatabase', () => {
  it('creates a fresh database without a backup', async () => {
    const db = openSqlJs(SQL);
    const files = new MemoryFileStore();
    expect(await bootDatabase(db, files, MIGRATIONS, opts)).toEqual({ schemaVersion: 1, migratedFrom: 0, restoredAfterRollback: false });
    expect(await listBackups(files)).toEqual([]);
  });

  it('takes a pre-migration backup when an update adds a migration', async () => {
    const db = openSqlJs(SQL);
    const files = new MemoryFileStore();
    await bootDatabase(db, files, MIGRATIONS, opts);
    await bootDatabase(db, files, [...MIGRATIONS, V2], { ...opts, bundleVersion: '0.2.0' });
    expect((await listBackups(files)).map((b) => [b.reason, b.schemaVersion])).toEqual([['pre-migration', 1]]);
  });

  it('restores the pre-update data when the shell rolled back a broken update', async () => {
    const db = openSqlJs(SQL);
    const files = new MemoryFileStore();
    await bootDatabase(db, files, MIGRATIONS, opts);
    await db.run("INSERT INTO settings VALUES ('k', 'before-update')");
    // bundle 0.2.0 migrates to v2, then fails to start
    await bootDatabase(db, files, [...MIGRATIONS, V2], { ...opts, bundleVersion: '0.2.0' });
    // the shell brings back 0.1.0 (schema v1) and tells it which version failed
    const res = await bootDatabase(db, files, MIGRATIONS, { bundleVersion: '0.1.0', rolledBackFrom: '0.2.0' });
    expect(res).toEqual({ schemaVersion: 1, migratedFrom: 2, restoredAfterRollback: true });
    expect(await getSchemaVersion(db)).toBe(1);
    expect(await db.all('SELECT value FROM settings')).toEqual([{ value: 'before-update' }]);
  });

  it('refuses to touch a newer database when no rollback happened', async () => {
    const db = openSqlJs(SQL);
    await migrate(db, [...MIGRATIONS, V2]);
    await expect(bootDatabase(db, new MemoryFileStore(), MIGRATIONS, opts)).rejects.toBeInstanceOf(DbNewerThanAppError);
  });
});
