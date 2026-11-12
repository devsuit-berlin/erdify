-- CREATE TABLE IF NOT EXISTS, and comments of both kinds.
/* A block comment before the first statement. */
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY, -- the key
    body TEXT NOT NULL /* inline */
);
