-- A composite foreign key pairs the columns in order, also when the names differ.
CREATE TABLE edition (book_id INTEGER, number INTEGER, PRIMARY KEY (book_id, number));
CREATE TABLE print_run (
    id INTEGER PRIMARY KEY,
    edition_book INTEGER NOT NULL,
    edition_number INTEGER NOT NULL,
    FOREIGN KEY (edition_book, edition_number) REFERENCES edition (book_id, number)
);
