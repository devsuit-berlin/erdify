-- A generated column is a column of the table (stored or virtual).
CREATE TABLE box (
    id INTEGER PRIMARY KEY,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    area INTEGER GENERATED ALWAYS AS (width * height) STORED,
    label TEXT AS ('box ' || id)
);
