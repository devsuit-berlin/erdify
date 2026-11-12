-- SQL identifiers are case-insensitive: REFERENCES Customer(ID) is customer.id.
CREATE TABLE customer (id INTEGER PRIMARY KEY);
CREATE TABLE invoice (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES Customer(ID),
    payer_id INTEGER,
    FOREIGN KEY (PAYER_ID) REFERENCES CUSTOMER (Id)
);
