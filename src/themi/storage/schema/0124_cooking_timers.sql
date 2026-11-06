-- RC3c: step timers. Each is also a scheduler job, so a restart doesn't lose one.
CREATE TABLE cooking_timers (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES cooking_sessions(id) ON DELETE SET NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    recipe TEXT NOT NULL,      -- the recipe's name, for the message
    step TEXT NOT NULL,        -- the step's label ("3", "2a")
    minutes REAL NOT NULL,
    ends_at TEXT NOT NULL,
    in_group INTEGER NOT NULL DEFAULT 0,
    fired_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX cooking_timers_running ON cooking_timers (member_id, fired_at, cancelled_at);
