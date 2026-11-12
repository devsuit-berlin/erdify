-- A column-level REFERENCES, nullable and NOT NULL, named and anonymous.
CREATE TABLE author (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE book (
    id INTEGER PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES author(id),
    editor_id INTEGER REFERENCES author (id) ON DELETE SET NULL,
    translator_id INTEGER CONSTRAINT fk_translator REFERENCES author(id)
);
