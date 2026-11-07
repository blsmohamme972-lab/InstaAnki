import initSqlJs, { type SqlJsStatic } from 'sql.js';
import { beforeAll, describe, expect, it } from 'vitest';
import { MemoryFileStore } from '../storage/files';
import { createBackup, findPreMigrationBackup, listBackups, parseBackup, restoreBackup, saveBackup } from './backup';
import { DbNewerThanAppError, getSchemaVersion, migrate } from './migrate';
import { LATEST_SCHEMA_VERSION, MIGRATIONS, type Migration } from './migrations';
import { openSqlJs } from './sqljs';
import type { Db } from './types';

let SQL: SqlJsStatic;
beforeAll(async () => {
  SQL = await initSqlJs();
});

const fresh = (): Db => openSqlJs(SQL);

const V2: Migration = { version: 2, name: 'add note', sql: 'ALTER TABLE cards ADD COLUMN note TEXT;' };

async function seed(db: Db): Promise<void> {
  await db.run("INSERT INTO packs VALUES ('p1', 1, 'Pack', 'ar', 'packs/p1/v1', 'manual', 1)");
  await db.run("INSERT INTO reels VALUES ('r1', 'p1', 1, 'Reel', '[]', 70.5, 'packs/p1/v1/reels/r1', 0, 0, 1)");
  await db.run("INSERT INTO cards (reel_id, created_at, liked) VALUES ('r1', 1, 1)");
  await db.run("INSERT INTO comments (reel_id, ts, video_time, text) VALUES ('r1', 5, 12.25, 'ملاحظة')");
}

describe('migrate', () => {
  it('creates the latest schema on an empty database without taking a backup', async () => {
    const db = fresh();
    let backups = 0;
    const res = await migrate(db, MIGRATIONS, { backup: async () => void backups++ });
    expect(res).toEqual({ from: 0, to: LATEST_SCHEMA_VERSION, applied: [1] });
    expect(backups).toBe(0);
    expect(await getSchemaVersion(db)).toBe(LATEST_SCHEMA_VERSION);
  });

  it('is idempotent', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    const again = await migrate(db, MIGRATIONS);
    expect(again.applied).toEqual([]);
  });

  it('backs up an existing database once before applying new migrations', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    const calls: number[] = [];
    const res = await migrate(db, [...MIGRATIONS, V2], { backup: async (v) => void calls.push(v) });
    expect(calls).toEqual([1]);
    expect(res.applied).toEqual([2]);
    await db.run("INSERT INTO cards (reel_id, created_at, note) VALUES ('x', 1, 'hi')");
  });

  it('refuses to run an app that is older than the database', async () => {
    const db = fresh();
    await migrate(db, [...MIGRATIONS, V2]);
    await expect(migrate(db, MIGRATIONS)).rejects.toBeInstanceOf(DbNewerThanAppError);
  });

  it('rolls back a failing migration completely', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    const bad: Migration = { version: 2, name: 'bad', sql: 'CREATE TABLE t1 (a INTEGER); SELECT * FROM missing_table;' };
    await expect(migrate(db, [...MIGRATIONS, bad])).rejects.toThrow();
    expect(await getSchemaVersion(db)).toBe(1);
    const t1 = await db.all("SELECT name FROM sqlite_master WHERE name = 't1'");
    expect(t1).toEqual([]);
  });

  it('rejects out-of-order migration lists', async () => {
    await expect(migrate(fresh(), [V2])).rejects.toThrow(/expected 1/);
  });
});

describe('transactions', () => {
  it('serializes concurrent transactions', async () => {
    const db = fresh();
    await db.exec('CREATE TABLE log (n INTEGER)');
    const order: string[] = [];
    const slow = db.transaction(async (tx) => {
      order.push('a-start');
      await new Promise((r) => setTimeout(r, 20));
      await tx.run('INSERT INTO log VALUES (1)');
      order.push('a-end');
    });
    const fast = db.transaction(async (tx) => {
      order.push('b-start');
      await tx.run('INSERT INTO log VALUES (2)');
      order.push('b-end');
    });
    await Promise.all([slow, fast]);
    expect(order).toEqual(['a-start', 'a-end', 'b-start', 'b-end']);
  });

  it('rolls back on error and keeps working afterwards', async () => {
    const db = fresh();
    await db.exec('CREATE TABLE log (n INTEGER)');
    await expect(
      db.transaction(async (tx) => {
        await tx.run('INSERT INTO log VALUES (1)');
        throw new Error('boom');
      }),
    ).rejects.toThrow('boom');
    await db.run('INSERT INTO log VALUES (2)');
    expect(await db.all('SELECT n FROM log')).toEqual([{ n: 2 }]);
  });
});

describe('backups', () => {
  it('round-trips every table, including unicode text and reals', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    await seed(db);
    const backup = parseBackup(JSON.stringify(await createBackup(db, 'manual', '0.1.0')));

    const other = fresh();
    await restoreBackup(other, backup, MIGRATIONS);
    expect(await getSchemaVersion(other)).toBe(1);
    expect(await other.all('SELECT text, video_time FROM comments')).toEqual([{ text: 'ملاحظة', video_time: 12.25 }]);
    expect(await other.all('SELECT reel_id, liked FROM cards')).toEqual([{ reel_id: 'r1', liked: 1 }]);
    // the restored database keeps working with normal migrations
    const res = await migrate(other, [...MIGRATIONS, V2]);
    expect(res.applied).toEqual([2]);
  });

  it('restores an older-schema backup into a newer database (bundle rollback case)', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    await seed(db);
    const files = new MemoryFileStore();
    await migrate(db, [...MIGRATIONS, V2], {
      backup: async () => void (await saveBackup(files, await createBackup(db, 'pre-migration', '0.1.0'))),
    });
    expect(await getSchemaVersion(db)).toBe(2);

    // the old bundle (knows only v1) comes back after a rollback
    const backup = await findPreMigrationBackup(files, 1);
    expect(backup).not.toBeNull();
    await restoreBackup(db, backup!, MIGRATIONS);
    expect(await getSchemaVersion(db)).toBe(1);
    expect(await db.all('SELECT id FROM reels')).toEqual([{ id: 'r1' }]);
    const cols = await db.all<{ name: string }>('PRAGMA table_info(cards)');
    expect(cols.map((c) => c.name)).not.toContain('note');
  });

  it('leaves the database untouched when a restore fails', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    await seed(db);
    const backup = await createBackup(db, 'manual', '0.1.0');
    backup.tables['not_a_table'] = [{ a: 1 }];
    await expect(restoreBackup(db, backup, MIGRATIONS)).rejects.toThrow(/unknown table/);
    expect(await db.all('SELECT id FROM reels')).toEqual([{ id: 'r1' }]);
  });

  it('refuses backups from a newer app', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    const backup = await createBackup(db, 'manual', '0.1.0');
    await expect(restoreBackup(db, { ...backup, schemaVersion: 99 }, MIGRATIONS)).rejects.toThrow(/newer/);
  });

  it('rejects files that are not backups', () => {
    expect(() => parseBackup('{"hello": 1}')).toThrow(/not an InstaAnki backup/);
  });

  it('keeps only the last 3 pre-migration backups', async () => {
    const db = fresh();
    await migrate(db, MIGRATIONS);
    const files = new MemoryFileStore();
    for (let i = 0; i < 5; i++) {
      await saveBackup(files, await createBackup(db, 'pre-migration', '0.1.0', new Date(Date.UTC(2026, 0, 1 + i))));
    }
    await saveBackup(files, await createBackup(db, 'manual', '0.1.0', new Date(Date.UTC(2026, 0, 9))));
    const list = await listBackups(files);
    expect(list.filter((b) => b.reason === 'pre-migration').map((b) => b.name.slice(0, 10))).toEqual([
      '2026-01-03',
      '2026-01-04',
      '2026-01-05',
    ]);
    expect(list.filter((b) => b.reason === 'manual')).toHaveLength(1);
  });
});
