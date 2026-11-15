-- OV2: the family's GE range (two ovens), through SmartHQ. The ovens are kept here, not
-- in `devices`: that table's provider CHECK can only change by rebuilding it, and a dozen
-- tables cascade from it.

-- The family's one SmartHQ sign-in: the app account's email and region, its password and
-- the refresh token the library rotates (both encrypted). `problem`: why it stopped working.
CREATE TABLE smarthq_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    email TEXT NOT NULL,
    region TEXT NOT NULL,
    password BLOB NOT NULL,                       -- encrypted
    refresh_token BLOB NOT NULL,                  -- encrypted
    problem TEXT,
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- One row per oven: the range's SmartHQ id and which of its ovens.
CREATE TABLE ovens (
    id INTEGER PRIMARY KEY,
    mac TEXT NOT NULL,
    cavity TEXT NOT NULL CHECK (cavity IN ('upper', 'lower')),
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mac, cavity)
);

-- What each oven last showed (OvenReading's fields).
CREATE TABLE oven_readings (
    oven_id INTEGER PRIMARY KEY REFERENCES ovens(id) ON DELETE CASCADE,
    state INTEGER NOT NULL,
    mode INTEGER NOT NULL,
    set_f INTEGER NOT NULL,
    temp_f INTEGER,
    timer_minutes INTEGER,
    cook_minutes_left INTEGER,
    remote INTEGER NOT NULL,
    probe_f INTEGER,
    read_at TEXT NOT NULL
);

-- Every write Themi sent, who asked, and whether the oven's state showed it took.
CREATE TABLE oven_actions (
    id INTEGER PRIMARY KEY,
    oven_id INTEGER NOT NULL REFERENCES ovens(id) ON DELETE CASCADE,
    what TEXT NOT NULL,                           -- heat, timer, off
    value TEXT NOT NULL,                          -- the raw ERD sent
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    sent_at TEXT NOT NULL,
    took INTEGER,
    state_after INTEGER,
    checked_at TEXT
);
CREATE INDEX oven_actions_oven ON oven_actions (oven_id, id);
