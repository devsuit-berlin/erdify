-- Link tables: a composite primary key made of foreign keys only.
CREATE TABLE post (id INTEGER PRIMARY KEY);
CREATE TABLE tag (id INTEGER PRIMARY KEY);
CREATE TABLE post_tag (
    post_id INTEGER NOT NULL REFERENCES post(id),
    tag_id INTEGER NOT NULL REFERENCES tag(id),
    PRIMARY KEY (post_id, tag_id)
);
CREATE TABLE post_rating (
    post_id INTEGER REFERENCES post(id),
    tag_id INTEGER REFERENCES tag(id),
    score INTEGER,
    PRIMARY KEY (post_id, tag_id)
);
