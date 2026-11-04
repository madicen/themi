-- CG1b: the litter box's chores.

-- A problem someone can fix (an error, an alert, sani-solution low or out, granules due),
-- and its chore: open until the box shows it's gone (cleared) or someone says it's done
-- (done). `gone_at`: the box stopped showing it; until then a done problem isn't raised
-- again. Granules have no sensor, so theirs is gone once done.
CREATE TABLE litter_problems (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    problem TEXT NOT NULL,
    detail TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'cleared')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    gone_at TEXT
);
CREATE INDEX litter_problems_live ON litter_problems (device_id, problem, gone_at);
CREATE INDEX litter_problems_task ON litter_problems (task_id);

-- The granules' chore, per litter box: every `every` cleaning cycles (off when NULL), counted
-- from `since_cycles`, its lifetime count when they were last topped up (or the count was
-- turned on).
CREATE TABLE litter_granules (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    every INTEGER CHECK (every IS NULL OR every > 0),
    since_cycles INTEGER
);
