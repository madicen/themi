-- V1: the robot vacuum, read from Roborock (the unofficial python-roborock library).

-- `devices` allows the 'roborock' provider. Rebuilding it would cascade-delete the rows
-- that point at it (foreign keys are on), so those are kept aside and put back.
CREATE TEMP TABLE kept_device_states AS SELECT * FROM device_states;
CREATE TEMP TABLE kept_cycles AS SELECT * FROM appliance_cycles;
CREATE TEMP TABLE kept_washers AS SELECT id, washer_id FROM laundry_loads;
CREATE TABLE devices_new (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL
        CHECK (provider IN ('lg_thinq', 'tuya', 'catgenie', 'home_connect', 'roborock')),
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    appliance TEXT,                               -- washer, dryer, vacuum...; NULL = unmapped
    credentials BLOB,                             -- encrypted, if the device has its own
    created_at TEXT NOT NULL,
    UNIQUE (provider, external_id)
);
INSERT INTO devices_new SELECT id, provider, external_id, name, appliance, credentials, created_at
FROM devices;
DROP TABLE devices;
ALTER TABLE devices_new RENAME TO devices;
INSERT INTO device_states SELECT * FROM kept_device_states
WHERE device_id NOT IN (SELECT device_id FROM device_states);
INSERT INTO appliance_cycles SELECT * FROM kept_cycles
WHERE id NOT IN (SELECT id FROM appliance_cycles);
UPDATE laundry_loads SET washer_id = (SELECT k.washer_id FROM kept_washers k
    WHERE k.id = laundry_loads.id) WHERE washer_id IS NULL;
DROP TABLE kept_device_states;
DROP TABLE kept_cycles;
DROP TABLE kept_washers;

-- The family's one Roborock sign-in: the app account's email and the library's login data
-- (its tokens and the robots' keys), encrypted. `problem`: why it stopped working.
CREATE TABLE roborock_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    email TEXT NOT NULL,
    login BLOB NOT NULL,                          -- encrypted
    problem TEXT,
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- What each robot last reported: its problems (kind -> words) and its worn parts
-- (counter -> part), as JSON. Changes become events.
CREATE TABLE vacuum_states (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    problems TEXT NOT NULL,
    parts TEXT NOT NULL,
    parts_read INTEGER NOT NULL DEFAULT 0,
    seen_at TEXT NOT NULL
);

-- A problem someone can fix, and its chore: open until the robot shows it's gone (cleared)
-- or someone says it's done (done). `gone_at`: the robot stopped showing it; until then a
-- done problem isn't raised again.
CREATE TABLE vacuum_problems (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    problem TEXT NOT NULL,                        -- the kind, or 'part:<part>'
    detail TEXT NOT NULL,
    room TEXT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'cleared')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    gone_at TEXT
);
CREATE INDEX vacuum_problems_live ON vacuum_problems (device_id, problem, gone_at);
CREATE INDEX vacuum_problems_task ON vacuum_problems (task_id);

INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('vacuum_home', 'Clear the vacuum''s alert and send it back to its dock, once someone''s sorted it',
     'family', 2, '1970-01-01T00:00:00+00:00');
