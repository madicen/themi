-- C3: Themi's check-ins as wall routines, and the morning and evening routine checks.
CREATE TABLE cozyla_routines (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    routine_id INTEGER NOT NULL UNIQUE,
    last_run INTEGER NOT NULL DEFAULT 0  -- the last task_runs id ticked on the wall
);
-- Routine ticks on the wall already acted on (`<routine id>_<day>`).
CREATE TABLE cozyla_routine_ticks (
    record TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
-- The morning and evening checks, once per person per part of the day.
CREATE TABLE routine_checks_sent (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    part TEXT NOT NULL,
    PRIMARY KEY (member_id, day, part)
);
