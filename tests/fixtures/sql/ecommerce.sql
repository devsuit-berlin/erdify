CREATE TYPE order_status AS ENUM ('pending', 'paid', 'shipped');

CREATE TABLE customer (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(120)
);

CREATE TABLE "order" (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    status order_status DEFAULT 'pending',
    total NUMERIC
);

CREATE TABLE product (id INTEGER PRIMARY KEY, sku VARCHAR(64) NOT NULL);

CREATE TABLE order_item (
    order_id INTEGER REFERENCES "order"(id),
    product_id INTEGER REFERENCES product(id),
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX ix_customer_email ON customer (email);
