import type { Database, SqlJsStatic } from 'sql.js';
import { createDb, type Db, type RawDriver, type Row, type SqlValue } from './types';

/** sql.js driver: used in the browser during development and in unit tests. Data lives in memory. */
export function sqlJsDriver(SQL: SqlJsStatic, data?: Uint8Array): RawDriver & { database: Database } {
  const database = new SQL.Database(data);
  database.exec('PRAGMA foreign_keys = OFF;');
  return {
    database,
    async exec(sql) {
      database.exec(sql);
    },
    async run(sql, params) {
      database.run(sql, params as SqlValue[]);
      return { changes: database.getRowsModified() };
    },
    async all(sql, params) {
      const stmt = database.prepare(sql);
      try {
        stmt.bind(params as SqlValue[]);
        const rows: Row[] = [];
        while (stmt.step()) rows.push(stmt.getAsObject() as Row);
        return rows;
      } finally {
        stmt.free();
      }
    },
    async begin() {
      database.exec('BEGIN');
    },
    async commit() {
      database.exec('COMMIT');
    },
    async rollback() {
      database.exec('ROLLBACK');
    },
    async close() {
      database.close();
    },
  };
}

export function openSqlJs(SQL: SqlJsStatic, data?: Uint8Array): Db {
  return createDb(sqlJsDriver(SQL, data));
}
