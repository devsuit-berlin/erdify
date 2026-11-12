-- A column-level PRIMARY KEY, INTEGER and non-INTEGER, with and without a name.
CREATE TABLE account (id INTEGER PRIMARY KEY, email TEXT);
CREATE TABLE country (code VARCHAR(2) PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE currency (iso CHAR(3) CONSTRAINT pk_currency PRIMARY KEY);
