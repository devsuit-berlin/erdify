-- CREATE UNIQUE INDEX on one column makes it unique, like a UNIQUE constraint.
-- A plain, composite, partial or expression index doesn't.
CREATE TABLE member (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    handle TEXT,
    first_name TEXT,
    last_name TEXT,
    referral TEXT,
    nickname TEXT
);
CREATE UNIQUE INDEX ux_member_email ON member (email);
CREATE INDEX ix_member_handle ON member (handle);
CREATE UNIQUE INDEX ux_member_name ON member (first_name, last_name);
CREATE UNIQUE INDEX ux_member_referral ON member (referral) WHERE referral IS NOT NULL;
CREATE UNIQUE INDEX ux_member_nickname ON member (lower(nickname));
