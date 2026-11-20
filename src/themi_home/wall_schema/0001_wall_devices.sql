-- WL1: the frames that show the wall page, and the codes that pair them.
-- A frame belongs to the household, not to a person. Its token and a pairing code are kept
-- only as hashes, like website sessions.
CREATE TABLE wall_devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    paired_by INTEGER REFERENCES members(id),
    paired_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE wall_pairing_codes (
    code_hash TEXT PRIMARY KEY,
    created_by INTEGER REFERENCES members(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

-- Wrong codes typed on a frame: five in ten minutes stop pairing for a while.
CREATE TABLE wall_pairing_misses (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL
);
