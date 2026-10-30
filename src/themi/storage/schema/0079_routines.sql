-- R1a: routines kept in Themi. Each person's routines are a name and a time window (local
-- time); `ends` NULL means until an hour before their quiet hours, as C3's evening check.
CREATE TABLE routines (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    starts TEXT NOT NULL,                         -- HH:MM
    ends TEXT,                                    -- HH:MM, or NULL
    created_at TEXT NOT NULL,
    UNIQUE (member_id, name COLLATE NOCASE)
);

-- Items on a routine: every day, on set days (`days`, 0 = Monday), or just one day.
CREATE TABLE routine_items (
    id INTEGER PRIMARY KEY,
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    days TEXT NOT NULL DEFAULT '[]',              -- JSON list; empty = every day
    only_on TEXT,                                 -- a date: just that day
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE routine_ticks (
    item_id INTEGER NOT NULL REFERENCES routine_items(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    ticked_at TEXT NOT NULL,
    PRIMARY KEY (item_id, day)
);

-- A routine's check for a day, once its window has ended (sent, or nothing was open).
CREATE TABLE routine_day_checks (
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (routine_id, day)
);

INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('routine_item_add', 'Add an item to someone else''s routine', 'member', 2,
     '1970-01-01T00:00:00+00:00');
