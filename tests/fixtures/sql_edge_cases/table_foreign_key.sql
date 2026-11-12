-- A table-level FOREIGN KEY, anonymous and named.
CREATE TABLE team (id INTEGER PRIMARY KEY);
CREATE TABLE player (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL,
    mentor_team_id INTEGER,
    FOREIGN KEY (team_id) REFERENCES team(id),
    CONSTRAINT fk_mentor FOREIGN KEY (mentor_team_id) REFERENCES team (id) ON DELETE CASCADE
);
