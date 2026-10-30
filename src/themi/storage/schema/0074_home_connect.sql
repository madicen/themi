-- H1: the dishwasher, read from Home Connect (Bosch, Siemens and other BSH appliances).
-- devices checks its providers, so it's rebuilt to allow 'home_connect'.
CREATE TABLE devices_new (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider IN ('lg_thinq', 'tuya', 'catgenie', 'home_connect')),
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    appliance TEXT,                               -- washer, dryer, feeder, litter_box; NULL = unmapped
    credentials BLOB,                             -- encrypted, if the device has its own
    created_at TEXT NOT NULL,
    UNIQUE (provider, external_id)
);
INSERT INTO devices_new SELECT id, provider, external_id, name, appliance, credentials, created_at
FROM devices;
DROP TABLE devices;
ALTER TABLE devices_new RENAME TO devices;

-- The family's one Home Connect sign-in: its appliances share it.
CREATE TABLE home_connect_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    refresh_token BLOB NOT NULL,                  -- encrypted
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- A link started from the Family page, for 10 minutes; only a hash of the state is kept.
CREATE TABLE home_connect_states (
    state_hash TEXT PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

-- Each appliance's last operation state read, and the dishwasher's cycles.
CREATE TABLE device_states (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    seen_at TEXT NOT NULL
);
CREATE TABLE appliance_cycles (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX appliance_cycles_started ON appliance_cycles (device_id, started_at);

-- The "running behind" signal, once a day at most.
CREATE TABLE dishwasher_pace (
    day TEXT PRIMARY KEY,
    runs INTEGER NOT NULL,
    usual REAL NOT NULL
);

INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('dishwasher_done', 'Check off the dishwasher routine when the dishwasher starts', 'family',
     2, '1970-01-01T00:00:00+00:00');
