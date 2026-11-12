-- Single-column UNIQUE (column-level, table-level, named) makes a column
-- unique; a composite UNIQUE doesn't make any one of its columns unique.
CREATE TABLE person (id INTEGER PRIMARY KEY);
CREATE TABLE passport (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL UNIQUE REFERENCES person(id),
    number TEXT CONSTRAINT uq_number UNIQUE,
    issuer TEXT,
    serial TEXT,
    country TEXT,
    batch TEXT,
    UNIQUE (issuer),
    CONSTRAINT uq_serial UNIQUE (serial),
    UNIQUE (country, batch)
);
