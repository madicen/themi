-- 35a: the household's saved takeout favourites (kept on the website), and the takeout
-- rescues staged, one a day at most.
CREATE TABLE takeout_favourites (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    store_url TEXT NOT NULL,
    items TEXT NOT NULL DEFAULT '[]',              -- JSON list of lines
    cents INTEGER NOT NULL CHECK (cents > 0),      -- about what it comes to, fees and tip in
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    removed_at TEXT
);

CREATE TABLE takeout_rescues (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL UNIQUE,                      -- the family's local date
    favourite_id INTEGER NOT NULL REFERENCES takeout_favourites(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    action_id INTEGER,
    staged_at TEXT NOT NULL
);
