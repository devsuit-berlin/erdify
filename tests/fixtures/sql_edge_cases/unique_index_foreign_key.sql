-- A foreign key made unique by CREATE UNIQUE INDEX is a one-to-one, like an
-- inline UNIQUE.
CREATE TABLE customer (id INTEGER PRIMARY KEY);
CREATE TABLE loyalty_card (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id)
);
CREATE UNIQUE INDEX ux_card_customer ON loyalty_card (customer_id);
