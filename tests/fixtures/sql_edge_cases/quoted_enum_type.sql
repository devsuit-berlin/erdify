-- PostgreSQL DDL (parsed with --sql-dialect postgres): a column typed with a
-- quoted enum name, which is read without its quotes, like the CREATE TYPE.
CREATE TYPE "order state" AS ENUM ('new', 'done');
CREATE TABLE "order" (id INTEGER PRIMARY KEY, state "order state" NOT NULL);
