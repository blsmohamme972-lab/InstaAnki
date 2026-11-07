export type SqlValue = string | number | null;
export type Row = Record<string, SqlValue>;

/** Minimal database API used by the whole app. Implemented over Capacitor SQLite (device) and sql.js (web/tests). */
export interface Db {
  /** Runs one or more statements without parameters. */
  exec(sql: string): Promise<void>;
  /** Runs one statement with parameters. */
  run(sql: string, params?: SqlValue[]): Promise<{ changes: number }>;
  /** Runs a query and returns all rows as objects. */
  all<T = Row>(sql: string, params?: SqlValue[]): Promise<T[]>;
  /** Runs `fn` inside a transaction; rolls back if it throws. Calls are serialized. */
  transaction<T>(fn: (tx: Db) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

/** Low-level driver; `createDb` adds locking and transaction semantics on top. */
export interface RawDriver {
  exec(sql: string): Promise<void>;
  run(sql: string, params: SqlValue[]): Promise<{ changes: number }>;
  all(sql: string, params: SqlValue[]): Promise<Row[]>;
  begin(): Promise<void>;
  commit(): Promise<void>;
  rollback(): Promise<void>;
  close(): Promise<void>;
}

/** Serializes all access so concurrent async callers cannot interleave inside a transaction. */
export function createDb(raw: RawDriver): Db {
  let queue: Promise<unknown> = Promise.resolve();

  function locked<T>(fn: () => Promise<T>): Promise<T> {
    const next = queue.then(fn, fn);
    queue = next.catch(() => undefined);
    return next;
  }

  const inTx: Db = {
    exec: (sql) => raw.exec(sql),
    run: (sql, params = []) => raw.run(sql, params),
    all: <T>(sql: string, params: SqlValue[] = []) => raw.all(sql, params) as Promise<T[]>,
    transaction: (fn) => fn(inTx), // nested: join the outer transaction
    close: () => Promise.reject(new Error('cannot close inside a transaction')),
  };

  return {
    exec: (sql) => locked(() => raw.exec(sql)),
    run: (sql, params = []) => locked(() => raw.run(sql, params)),
    all: <T>(sql: string, params: SqlValue[] = []) => locked(() => raw.all(sql, params) as Promise<T[]>),
    transaction: <T>(fn: (tx: Db) => Promise<T>) =>
      locked(async () => {
        await raw.begin();
        try {
          const result = await fn(inTx);
          await raw.commit();
          return result;
        } catch (err) {
          await raw.rollback();
          throw err;
        }
      }),
    close: () => locked(() => raw.close()),
  };
}
