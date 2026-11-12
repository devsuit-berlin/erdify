-- A bare REFERENCES t (no column list) references t's primary key, whatever
-- its name.
CREATE TABLE country (code CHAR(2) PRIMARY KEY, name TEXT);
CREATE TABLE city (
    id INTEGER PRIMARY KEY,
    country_code CHAR(2) NOT NULL REFERENCES country
);
CREATE TABLE region (
    id INTEGER PRIMARY KEY,
    country_code CHAR(2),
    FOREIGN KEY (country_code) REFERENCES country
);
