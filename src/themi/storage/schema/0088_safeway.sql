-- 35c: the Safeway helper (the Chrome extension) and its cart jobs.

-- A paired helper: its token is shown once and kept only as a hash.
CREATE TABLE safeway_helpers (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);

-- A cart to fill: queued when someone says yes, claimed once by a helper, then answered
-- (done) or expired (the links fallback went instead).
CREATE TABLE safeway_jobs (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    action_id INTEGER,
    items TEXT NOT NULL,           -- JSON: [{"name": ..., "qty": ...}]
    status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'done', 'expired')),
    helper_id INTEGER REFERENCES safeway_helpers(id) ON DELETE SET NULL,
    results TEXT,                  -- JSON, as validated
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    finished_at TEXT
);
CREATE INDEX safeway_jobs_open ON safeway_jobs (status) WHERE status IN ('queued', 'claimed');

-- What an item on the list means at Safeway, shared by both browsers.
CREATE TABLE safeway_products (
    name_key TEXT PRIMARY KEY,     -- the grocery item, lowercase and single-spaced
    name TEXT NOT NULL,
    product_id TEXT,               -- Safeway's pid; NULL until a fill picks one
    product_name TEXT,
    size TEXT,
    search_words TEXT,             -- what to search for instead of the item's name
    updated_at TEXT NOT NULL
);
