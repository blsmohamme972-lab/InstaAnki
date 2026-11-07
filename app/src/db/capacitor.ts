import { CapacitorSQLite, SQLiteConnection } from '@capacitor-community/sqlite';
import { createDb, type Db, type Row } from './types';

export const DB_NAME = 'instaanki';

/** Device driver over @capacitor-community/sqlite (a real SQLite file in the app's private storage). */
export async function openCapacitorDb(): Promise<Db> {
  const sqlite = new SQLiteConnection(CapacitorSQLite);
  const consistent = (await sqlite.checkConnectionsConsistency()).result;
  const exists = (await sqlite.isConnection(DB_NAME, false)).result;
  const conn =
    consistent && exists
      ? await sqlite.retrieveConnection(DB_NAME, false)
      : await sqlite.createConnection(DB_NAME, false, 'no-encryption', 1, false);
  await conn.open();

  return createDb({
    async exec(sql) {
      await conn.execute(sql, false);
    },
    async run(sql, params) {
      const res = await conn.run(sql, params, false);
      return { changes: res.changes?.changes ?? 0 };
    },
    async all(sql, params) {
      const res = await conn.query(sql, params);
      return (res.values ?? []) as Row[];
    },
    async begin() {
      await conn.beginTransaction();
    },
    async commit() {
      await conn.commitTransaction();
    },
    async rollback() {
      await conn.rollbackTransaction();
    },
    async close() {
      await conn.close();
      await sqlite.closeConnection(DB_NAME, false);
    },
  });
}
