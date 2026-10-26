-- C2b: Themi's chores on the wall's chore chart, Themi in charge.
-- A chore either of you can do, every round (the wall's "AnyOne" with both of you).
ALTER TABLE tasks ADD COLUMN either INTEGER NOT NULL DEFAULT 0;

-- Each Themi chore's chore on the wall.
CREATE TABLE cozyla_chores (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    chore_uid TEXT NOT NULL UNIQUE,
    last_run INTEGER NOT NULL DEFAULT 0  -- the last task_runs id ticked on the wall
);
-- Ticks on the wall already acted on (`<chore uid>_<member uid>_<day>`), so none counts twice.
CREATE TABLE cozyla_chore_ticks (
    record TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
-- Set once the first chore sync has run.
CREATE TABLE cozyla_chore_sync (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    synced_at TEXT NOT NULL
);
