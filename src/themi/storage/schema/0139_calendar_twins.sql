-- F34e (idea #175): the same event twice. A read event keeps how many other guests it has
-- and whether it's part of a series: meetings and series are left alone.
ALTER TABLE calendar_entries ADD COLUMN guests INTEGER NOT NULL DEFAULT 0;
ALTER TABLE calendar_entries ADD COLUMN recurring INTEGER NOT NULL DEFAULT 0;

-- "Same event on two calendars": ask (a card), guess (Themi's best guess, with an undo for
-- a day) or keep (both stay as they are).
ALTER TABLE members ADD COLUMN calendar_twins TEXT NOT NULL DEFAULT 'ask';

-- Merging two copies of one event that Themi found. Twins on one calendar with the same
-- title, times and place are merged on its own (done, then told); the family can change it.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('calendar_twins', 'Merge the same event found twice', 'member', 2, 2,
     '1970-01-01T00:00:00+00:00');

-- Each pair Themi has seen once, by its two event ids (sorted), so it's never asked again.
-- answer: asked, merged, guessed, both, mine, family, auto, apart (not the same), kept.
CREATE TABLE calendar_twins (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    first_id TEXT NOT NULL,
    second_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    action_id INTEGER,
    undo TEXT,  -- JSON: what a best-guess merge changed, to put back (for a day)
    seen_at TEXT NOT NULL,
    answered_at TEXT,
    UNIQUE (member_id, first_id, second_id)
);
