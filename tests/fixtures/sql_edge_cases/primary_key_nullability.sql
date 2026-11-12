-- SQLite lets a non-INTEGER or composite primary key of a rowid table hold
-- NULL (a documented legacy bug); like the SQL standard, a primary key is
-- never nullable.
CREATE TABLE tag (slug TEXT PRIMARY KEY);
CREATE TABLE tag_alias (slug TEXT, alias TEXT, PRIMARY KEY (slug, alias));
