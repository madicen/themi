-- K4: travel time and "time to get ready" for events with a place.

-- Per person: how long getting ready takes, and whether they want the heads-up.
ALTER TABLE members ADD COLUMN getting_ready_minutes INTEGER NOT NULL DEFAULT 15;
ALTER TABLE members ADD COLUMN leave_heads_up INTEGER NOT NULL DEFAULT 1;

-- The family's home, as typed and as found on the map (one row).
CREATE TABLE family_home (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    address TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    set_at TEXT NOT NULL
);

-- Places already looked up (found = 0: not found; tried again after a day).
CREATE TABLE geocodes (
    query_key TEXT PRIMARY KEY,
    lat REAL,
    lon REAL,
    found INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);

-- Heads-ups sent, one per event and start time (a moved event gets a new one).
CREATE TABLE travel_headsups (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (member_id, event_id, starts_at)
);
