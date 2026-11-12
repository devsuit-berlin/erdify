-- A foreign key to a table defined further down, and one to its own table.
CREATE TABLE employee (
    id INTEGER PRIMARY KEY,
    manager_id INTEGER REFERENCES employee(id),
    department_id INTEGER NOT NULL REFERENCES department(id)
);
CREATE TABLE department (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
