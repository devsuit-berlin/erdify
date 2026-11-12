-- Reserved words and other quoted names as table and column names.
CREATE TABLE "order" (id INTEGER PRIMARY KEY, "group" TEXT NOT NULL);
CREATE TABLE "order line" (
    "order" INTEGER NOT NULL REFERENCES "order"(id),
    "line no" INTEGER,
    PRIMARY KEY ("order", "line no")
);
