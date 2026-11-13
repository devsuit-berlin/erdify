-- A primary key is unique by definition; an extra UNIQUE on a sole primary key
-- doesn't mark it. A UNIQUE on one column of a composite primary key does: the
-- column is unique on its own (#331).
CREATE TABLE badge (id INTEGER PRIMARY KEY UNIQUE);
CREATE TABLE seat (row_no INTEGER, seat_no INTEGER, UNIQUE (row_no), PRIMARY KEY (row_no, seat_no));
-- A link table whose member is unique: each person has at most one row (1:N, not M:N).
CREATE TABLE person (id INTEGER PRIMARY KEY);
CREATE TABLE tenant (id INTEGER PRIMARY KEY);
CREATE TABLE person_tenant (
    person_id INTEGER UNIQUE REFERENCES person (id),
    tenant_id INTEGER REFERENCES tenant (id),
    PRIMARY KEY (person_id, tenant_id)
);
CREATE TABLE desk (room INTEGER, desk_no INTEGER, owner_id INTEGER REFERENCES person (id),
    PRIMARY KEY (room, desk_no, owner_id));
CREATE UNIQUE INDEX desk_owner ON desk (owner_id);
