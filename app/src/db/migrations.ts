/**
 * Forward-only schema migrations. NEVER edit a migration that has shipped; add a new one.
 * Each migration runs inside one transaction together with its schema_version row.
 */
export interface Migration {
  version: number;
  name: string;
  sql: string;
}

export const MIGRATIONS: Migration[] = [
  {
    version: 1,
    name: 'initial schema',
    sql: `
      CREATE TABLE packs (
        id          TEXT PRIMARY KEY,
        version     INTEGER NOT NULL,
        title       TEXT NOT NULL,
        language    TEXT NOT NULL,
        path        TEXT NOT NULL,
        source      TEXT NOT NULL,
        imported_at INTEGER NOT NULL
      );

      CREATE TABLE reels (
        id          TEXT PRIMARY KEY,
        pack_id     TEXT NOT NULL,
        revision    INTEGER NOT NULL,
        title       TEXT NOT NULL,
        tags        TEXT NOT NULL,
        duration    REAL NOT NULL,
        path        TEXT NOT NULL,
        order_index INTEGER NOT NULL,
        removed     INTEGER NOT NULL DEFAULT 0,
        updated_at  INTEGER NOT NULL
      );
      CREATE INDEX reels_pack ON reels(pack_id, order_index);

      CREATE TABLE cards (
        reel_id         TEXT PRIMARY KEY,
        state           TEXT NOT NULL DEFAULT 'new'
                        CHECK (state IN ('new', 'learning', 'review', 'relearning')),
        due             INTEGER,
        stability       REAL,
        difficulty      REAL,
        reps            INTEGER NOT NULL DEFAULT 0,
        lapses          INTEGER NOT NULL DEFAULT 0,
        last_review     INTEGER,
        liked           INTEGER NOT NULL DEFAULT 0,
        suspended       INTEGER NOT NULL DEFAULT 0,
        skip_count      INTEGER NOT NULL DEFAULT 0,
        difficulty_hint INTEGER NOT NULL DEFAULT 0,
        leech           INTEGER NOT NULL DEFAULT 0,
        created_at      INTEGER NOT NULL
      );
      CREATE INDEX cards_due ON cards(state, due);

      CREATE TABLE review_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        reel_id     TEXT NOT NULL,
        ts          INTEGER NOT NULL,
        format      TEXT NOT NULL,
        question_id TEXT,
        correct     INTEGER,
        response_ms INTEGER,
        grade       INTEGER,
        speed       REAL,
        graded      INTEGER NOT NULL DEFAULT 1
      );
      CREATE INDEX review_log_reel ON review_log(reel_id, ts);

      CREATE TABLE probe_stats (
        reel_id     TEXT NOT NULL,
        probe_key   TEXT NOT NULL,
        shown       INTEGER NOT NULL DEFAULT 0,
        correct     INTEGER NOT NULL DEFAULT 0,
        last_shown  INTEGER,
        last_format TEXT,
        PRIMARY KEY (reel_id, probe_key)
      );

      CREATE TABLE comments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        reel_id    TEXT NOT NULL,
        ts         INTEGER NOT NULL,
        video_time REAL,
        text       TEXT NOT NULL
      );
      CREATE INDEX comments_reel ON comments(reel_id);

      CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `,
  },
];

export const LATEST_SCHEMA_VERSION = MIGRATIONS[MIGRATIONS.length - 1]!.version;
