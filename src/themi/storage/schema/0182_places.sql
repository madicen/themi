-- F57b: places they name instead of an address ("Stanford" -> the visitor parking lot),
-- with what's worth knowing whenever they go (visiting hours) and how many minutes early
-- they like to get there. Household places are shared; personal ones are seen only by
-- their owner, as facts are.
CREATE TABLE places (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('family', 'member')),
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',          -- comma-separated other names
    address TEXT NOT NULL,                     -- where to go
    note TEXT NOT NULL DEFAULT '',             -- e.g. visiting hours
    arrive_early INTEGER NOT NULL DEFAULT 0,   -- minutes before an event there to arrive
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((scope = 'member') = (member_id IS NOT NULL)),
    CHECK (arrive_early BETWEEN 0 AND 120)
);

-- F57b: a pinned fact that hasn't come up in 8 weeks is unpinned. `last_matched_at`: the
-- last time it matched what someone said or looked up (unlike `last_shown_at`, which a
-- pinned fact gets on every request). `pinned_at`: when it was pinned, counted from when it
-- has never matched. `unpinned_at`: when the job unpinned it, for the page.
ALTER TABLE facts ADD COLUMN last_matched_at TEXT;
ALTER TABLE facts ADD COLUMN pinned_at TEXT;
ALTER TABLE facts ADD COLUMN unpinned_at TEXT;
-- Facts pinned before this count from the update, so none is unpinned for 8 weeks after it.
UPDATE facts SET pinned_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') WHERE pinned = 1;
