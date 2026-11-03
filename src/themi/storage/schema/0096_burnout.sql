-- F22d (Erin's ideas #33, #122, #123): burnout mode holds everything with no end date, and
-- hands time-sensitive tasks to the partner until it ends.
CREATE TABLE burnout (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    pause_id INTEGER NOT NULL REFERENCES pauses (id),
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX burnout_member ON burnout (member_id, ended_at);
CREATE TABLE burnout_handoffs (
    id INTEGER PRIMARY KEY,
    burnout_id INTEGER NOT NULL REFERENCES burnout (id),
    task_id INTEGER NOT NULL REFERENCES tasks (id),
    from_member INTEGER NOT NULL REFERENCES members (id),
    to_member INTEGER NOT NULL REFERENCES members (id),
    created_at TEXT NOT NULL
);
-- Each check-in's place in burnout mode: held with the rest, kept (in its own burnout
-- words, if they gave some), or sent only while burnout mode is on.
ALTER TABLE habits ADD COLUMN burnout TEXT NOT NULL DEFAULT 'held'
    CHECK (burnout IN ('held', 'keep', 'only'));
ALTER TABLE habits ADD COLUMN burnout_prompt TEXT;
