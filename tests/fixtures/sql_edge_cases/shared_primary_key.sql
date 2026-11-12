-- A primary key that is also a foreign key (a one-to-one by shared key), and
-- a composite key whose part references another table.
CREATE TABLE "user" (id INTEGER PRIMARY KEY);
CREATE TABLE user_profile (id INTEGER PRIMARY KEY REFERENCES "user"(id), bio TEXT);
CREATE TABLE user_login (
    user_id INTEGER REFERENCES "user"(id),
    at TIMESTAMP,
    PRIMARY KEY (user_id, at)
);
