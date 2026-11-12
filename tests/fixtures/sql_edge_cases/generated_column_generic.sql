-- Without --sql-dialect, sqlglot can't parse a generated column with STORED /
-- VIRTUAL (a documented limitation): that table is skipped, the rest of the
-- file is still read.
CREATE TABLE plain (id INTEGER PRIMARY KEY);
CREATE TABLE box (
    id INTEGER PRIMARY KEY,
    width INTEGER NOT NULL,
    area INTEGER GENERATED ALWAYS AS (width * 2) STORED
);
