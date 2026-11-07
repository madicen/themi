-- BD1a: body double sessions (Erin's spec, 2026-11-06). One row per session; a switch of
-- mode ends the row as `switched` and starts a new one that keeps the start time. The
-- hour of the week and the energy level at the start are for learning (BD2) only, and are
-- never shown.
CREATE TABLE body_double_sessions (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    task_id INTEGER REFERENCES tasks (id),
    label TEXT NOT NULL,              -- the task's title, or their own words ("my writing")
    category TEXT,                    -- BD2
    mode TEXT NOT NULL,               -- silent, sprint or guided
    started_at TEXT NOT NULL,
    planned_minutes INTEGER,          -- NULL: until they say they're done (four hours at most)
    work_minutes INTEGER NOT NULL,
    break_minutes INTEGER NOT NULL,
    blocks_done INTEGER NOT NULL DEFAULT 0,
    hour_of_week INTEGER NOT NULL,    -- 0 is Monday midnight, local time
    energy_level TEXT,                -- low, medium or high at the start; internal only
    phase TEXT NOT NULL,              -- work, break or asking
    asking TEXT,                      -- what's being asked: end, work_end or break_end
    phase_ends_at TEXT,
    seq INTEGER NOT NULL DEFAULT 0,   -- bumped at each change; a job or button from before is stale
    pause_id INTEGER REFERENCES pauses (id),
    ask_outbox_id INTEGER,
    switched_from INTEGER REFERENCES body_double_sessions (id),
    ended_at TEXT,
    outcome TEXT                      -- finished, stopped, left or switched
);
CREATE INDEX body_double_member ON body_double_sessions (member_id, ended_at);
ALTER TABLE members ADD COLUMN sprint_work_minutes INTEGER NOT NULL DEFAULT 25;
ALTER TABLE members ADD COLUMN sprint_break_minutes INTEGER NOT NULL DEFAULT 5;
