-- PostgreSQL DDL (parsed with --sql-dialect postgres): an enum type, SERIAL
-- keys and function defaults.
CREATE TYPE ticket_state AS ENUM ('open', 'closed');
CREATE TABLE queue (id SERIAL PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE ticket (
    id BIGSERIAL PRIMARY KEY,
    queue_id INT NOT NULL REFERENCES queue(id),
    state ticket_state NOT NULL DEFAULT 'open',
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
