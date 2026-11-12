-- SQLite table options (parsed with --sql-dialect sqlite): WITHOUT ROWID and STRICT.
CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB) WITHOUT ROWID;
CREATE TABLE reading (
    id INTEGER PRIMARY KEY,
    kv_key TEXT NOT NULL REFERENCES kv(key),
    value REAL
) STRICT;
