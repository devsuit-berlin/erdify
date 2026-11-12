-- A table-level PRIMARY KEY, single and composite, anonymous and named.
CREATE TABLE setting (name TEXT, value TEXT, PRIMARY KEY (name));
CREATE TABLE calendar_day (year INTEGER, day INTEGER, note TEXT, PRIMARY KEY (year, day));
CREATE TABLE shift (
    site TEXT,
    starts_at TIMESTAMP,
    staff INTEGER NOT NULL,
    CONSTRAINT pk_shift PRIMARY KEY (site, starts_at)
);
