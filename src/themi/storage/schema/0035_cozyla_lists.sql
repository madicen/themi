-- C1c: every list on the wall is watched, not just the configured one.
-- A link remembers which list its to-do belongs on (NULL: the configured list, or
-- wherever the to-do already is), so a task can be put on "Things to Cook".
ALTER TABLE cozyla_links ADD COLUMN list_id TEXT;
-- Each list's name, as of the last sync, for the tools that name a list.
ALTER TABLE cozyla_sync ADD COLUMN title TEXT NOT NULL DEFAULT '';

-- Items for a wall list that aren't anyone's task ("lasagna for Things to Cook").
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('wall_list_add', 'Add items to a list on the Cozyla wall', 'family', 2,
     '1970-01-01T00:00:00+00:00');
