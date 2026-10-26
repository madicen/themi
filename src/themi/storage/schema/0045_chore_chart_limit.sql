-- C2d (Erin's ideas #16 and #17): only so many of a person's chores on the wall's chore
-- chart at a time; the rest wait in Themi.
ALTER TABLE members ADD COLUMN chart_limit INTEGER NOT NULL DEFAULT 0;  -- 0: no limit
-- The chores up on a person's chart now. A pick lasts while its round does (due_on as it
-- was when picked), so it stays up across days until it's done or the round moves.
CREATE TABLE cozyla_chart_picks (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    due_on TEXT,                          -- the round it was picked for
    extra INTEGER NOT NULL DEFAULT 0,     -- "another one": on top of the limit
    prompted INTEGER NOT NULL DEFAULT 0,  -- its nudge has been sent for
    picked_at TEXT NOT NULL,
    PRIMARY KEY (member_id, task_id)
);
-- "A different one": that chore isn't picked again for the person that day.
CREATE TABLE cozyla_chart_skips (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (member_id, task_id, day)
);
