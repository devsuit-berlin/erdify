-- NOT NULL / explicit NULL / no constraint, defaults and CHECK constraints
-- don't change nullability.
CREATE TABLE item (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    label TEXT NULL,
    note TEXT,
    qty INTEGER NOT NULL DEFAULT 0,
    price NUMERIC DEFAULT 1.5 CHECK (price >= 0),
    code TEXT CONSTRAINT nn_code NOT NULL,
    CHECK (qty >= 0)
);
