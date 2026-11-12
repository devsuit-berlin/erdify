-- A primary key is unique by definition; an extra UNIQUE on it doesn't mark
-- it, and a UNIQUE on one column of a composite primary key leaves it a key part.
CREATE TABLE badge (id INTEGER PRIMARY KEY UNIQUE);
CREATE TABLE seat (row_no INTEGER, seat_no INTEGER, UNIQUE (row_no), PRIMARY KEY (row_no, seat_no));
