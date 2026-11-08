-- SP5: what admins did on the Modules page (changes, tests, restarts), newest last. Never
-- a secret's value: only that it was set or cleared.
CREATE TABLE config_audit (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    what TEXT NOT NULL,
    at TEXT NOT NULL
);
