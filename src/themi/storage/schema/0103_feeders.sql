-- 32: the pet feeders, read from Tuya's cloud (the SmartLife app's devices).

-- The family's one Tuya cloud project: its Access ID, its Access Secret (encrypted) and its
-- data centre. `problem`: why it stopped working (a secret changed, the free plan lapsed).
CREATE TABLE tuya_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_id TEXT NOT NULL,
    secret BLOB NOT NULL,                         -- encrypted
    region TEXT NOT NULL,
    problem TEXT,
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- What each Tuya device is and last said, raw: its category and product, its specification
-- (the data points' types, ranges and labels) and its status, as Tuya sent them (JSON).
-- Kept so a model's data points can be read and captured (`themi tuya capture`).
CREATE TABLE tuya_devices (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    product_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    spec TEXT,
    status TEXT,
    read_at TEXT
);

-- What each feeder last showed: its problems (kind -> words) as JSON, and its food level
-- when it reports one. Changes become events; the first read is the starting point.
-- `feeds_to`: how far its feeding log has been read.
CREATE TABLE feeder_states (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    problems TEXT NOT NULL,
    level INTEGER,
    feeds_to TEXT,
    seen_at TEXT NOT NULL
);

-- A problem someone can fix (food low or out, a jam, a fault), and its chore: open until
-- the feeder shows it's gone (cleared) or someone says it's done (done). `gone_at`: the
-- feeder stopped showing it; until then a done problem isn't raised again.
CREATE TABLE feeder_problems (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    problem TEXT NOT NULL,
    detail TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'cleared')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    gone_at TEXT
);
CREATE INDEX feeder_problems_live ON feeder_problems (device_id, problem, gone_at);
CREATE INDEX feeder_problems_task ON feeder_problems (task_id);

-- Each feeding the feeder reported (its log): how many portions, and when.
CREATE TABLE feeder_feeds (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    portions INTEGER NOT NULL,
    fed_at TEXT NOT NULL,
    UNIQUE (device_id, fed_at)
);
