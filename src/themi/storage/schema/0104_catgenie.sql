-- CG1a: the CatGenie litter box, read from the CatGenie app's cloud (PetNovations).

-- The family's one CatGenie sign-in: its refresh token (encrypted). The phone number it was
-- made with isn't kept. `problem`: why it stopped working (PetNovations refused it).
-- `alerts_read`: its notifications have been read once (that first read is the starting point).
CREATE TABLE catgenie_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    refresh_token BLOB NOT NULL,                  -- encrypted
    problem TEXT,
    alerts_read INTEGER NOT NULL DEFAULT 0,
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- What each litter box last reported, raw, as PetNovations sent it (JSON). Kept so its
-- fields can be read and captured (`themi catgenie capture`).
CREATE TABLE catgenie_devices (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    raw TEXT NOT NULL,
    read_at TEXT NOT NULL
);

-- Each notification the app was sent, raw (its `data` JSON), once. `device_id`: the litter
-- box it's about, when it's one of Themi's. The first read keeps what's there as already
-- seen (`first`), so old alerts never become chores.
CREATE TABLE catgenie_notifications (
    id TEXT PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    created_at TEXT,
    first INTEGER NOT NULL DEFAULT 0,
    seen_at TEXT NOT NULL
);

-- What each litter box last showed: its problems (kind -> words) as JSON, its sani-solution
-- and cycle count. Changes become events; the first read is the starting point. `alert`: an
-- error the app was alerted about (in words), live from `alert_at` until a clean after it.
CREATE TABLE litter_states (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    problems TEXT NOT NULL,
    sani_left INTEGER,
    cycles INTEGER,
    alert TEXT,
    alert_at TEXT,
    seen_at TEXT NOT NULL
);
