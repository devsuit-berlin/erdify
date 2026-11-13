-- Names a diagram grammar can't take as they are (#288): spaces, punctuation,
-- quotes, digits first, Mermaid keywords and keys, non-ASCII letters.
CREATE TABLE "Order Items" (
    "Item Key" INTEGER PRIMARY KEY,
    "uk" INTEGER,
    "PK" INTEGER,
    "fk-ref" INTEGER,
    "1st" INTEGER,
    "a,b" INTEGER,
    "(x)" TEXT,
    "a""b" INTEGER UNIQUE,
    "größe" TEXT DEFAULT 'x "y" ~z~',
    "naïve°" TEXT,
    "a~b~c" TEXT,
    "direction LR" TEXT,
    "100% done" INTEGER
);
CREATE TABLE "Line-Note" (
    id INTEGER PRIMARY KEY,
    "Item Key" INTEGER REFERENCES "Order Items"("Item Key"),
    "a""b" INTEGER REFERENCES "Order Items"("a""b")
);
CREATE TABLE "one" (id INTEGER PRIMARY KEY, "to" INTEGER REFERENCES "to-do"(id));
CREATE TABLE "to-do" (id INTEGER PRIMARY KEY);
CREATE TABLE "Class" (id INTEGER PRIMARY KEY, "one" INTEGER REFERENCES "one"(id));
CREATE TABLE "direction TB" (id INTEGER PRIMARY KEY, "x" INTEGER REFERENCES "a%b\c"(id));
CREATE TABLE "a%b\c" (id INTEGER PRIMARY KEY);
CREATE TABLE "a b" (id INTEGER PRIMARY KEY, "a_b" INTEGER REFERENCES "a_b"(id));
CREATE TABLE "a_b" (id INTEGER PRIMARY KEY, "a b" INTEGER REFERENCES "a b"(id));
CREATE TABLE "Größe" (id INTEGER PRIMARY KEY, "1" INTEGER REFERENCES "Class"(id));
