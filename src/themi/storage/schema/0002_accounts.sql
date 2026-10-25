-- The one family this server belongs to. The CHECK keeps it to a single row.
CREATE TABLE family (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    takeout_budget_cents INTEGER NOT NULL DEFAULT 0 CHECK (takeout_budget_cents >= 0),
    staples TEXT NOT NULL DEFAULT '[]',          -- JSON list of item names
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE members (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    telegram_user_id INTEGER UNIQUE,
    quiet_start TEXT NOT NULL DEFAULT '21:30',   -- local time, HH:MM
    quiet_end TEXT NOT NULL DEFAULT '08:00',
    daily_limit INTEGER NOT NULL DEFAULT 6,       -- proactive messages per day
    pda_enabled INTEGER NOT NULL DEFAULT 1,
    pda_strength INTEGER NOT NULL DEFAULT 2 CHECK (pda_strength BETWEEN 0 AND 3),
    recovery_hours REAL NOT NULL DEFAULT 6.0,     -- half-life of a drained state
    tracking TEXT NOT NULL DEFAULT '{}',          -- JSON: input name -> on/off
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE linked_accounts (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('gmail')),
    address TEXT NOT NULL COLLATE NOCASE,
    refresh_token BLOB NOT NULL,                  -- encrypted
    watched INTEGER NOT NULL DEFAULT 1,
    labels TEXT NOT NULL DEFAULT '[]',            -- JSON list of labels to watch
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (provider, address)
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider IN ('lg_thinq', 'tuya', 'catgenie')),
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    appliance TEXT,                               -- washer, dryer, feeder, litter_box; NULL = unmapped
    credentials BLOB,                             -- encrypted, if the device has its own
    created_at TEXT NOT NULL,
    UNIQUE (provider, external_id)
);

-- One-time codes a member sends as `/start <code>` to pair their Telegram account.
-- Only a hash of the code is stored.
CREATE TABLE invites (
    code_hash TEXT PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE message_log (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    telegram_message_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX message_log_member_time ON message_log (member_id, created_at);
