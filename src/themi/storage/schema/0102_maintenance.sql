-- 33: seasonal and long-term maintenance (filter changes, gutters, fertilizing the trees).
-- An item comes due `interval_days` after it was last done (or on `first_due`), only in
-- its active months (JSON month numbers, [] for all year). `guide`: its steps, as JSON.
-- `task_id`: the task it's offered as, while that's open. `offered_at`: when it last was,
-- for at most one new offer a day. `skip_until`: offered and turned down, not before then.
CREATE TABLE maintenance_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    interval_days INTEGER NOT NULL CHECK (interval_days >= 1),
    active_months TEXT NOT NULL DEFAULT '[]',
    guide TEXT NOT NULL DEFAULT '[]',
    owner INTEGER REFERENCES members(id) ON DELETE SET NULL,  -- NULL: whoever has room
    first_due TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    offered_at TEXT,
    skip_until TEXT,
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

-- Each time it was done, by whom, and what they noted ("the 16x25 filter, from the shed").
CREATE TABLE maintenance_runs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES maintenance_items(id) ON DELETE CASCADE,
    done_on TEXT NOT NULL,
    done_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    notes TEXT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX maintenance_runs_item ON maintenance_runs (item_id, done_on);

-- The family calendar (26) shows each item's next due date: `calendar_events.source`
-- allows 'maintenance'. Nothing points at the table, so it's rebuilt as it is.
CREATE TABLE calendar_events_new (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('task', 'maintenance')),
    source_id INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    calendar_id TEXT,                              -- where it was written
    state TEXT NOT NULL DEFAULT 'approved' CHECK (state IN ('approved', 'synced', 'deleted')),
    synced_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);
INSERT INTO calendar_events_new SELECT * FROM calendar_events;
DROP TABLE calendar_events;
ALTER TABLE calendar_events_new RENAME TO calendar_events;
