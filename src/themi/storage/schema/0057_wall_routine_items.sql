-- Bug #22: "add 'replace vacuum water' to my evening routine" went to the calendar, then the
-- chore chart, then a new list. Items for a routine on the wall now have their own tool.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('wall_routine_add', 'Add an item to a routine on the Cozyla wall', 'member', 2,
     '1970-01-01T00:00:00+00:00');

-- The wall's routines repeat and have no end, so a just-for-today item is deleted the day
-- after (its tick stays in the wall's history).
CREATE TABLE wall_routine_once (
    routine_id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    day TEXT NOT NULL
);
