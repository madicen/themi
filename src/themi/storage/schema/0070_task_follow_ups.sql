-- F17b (Erin's bug #70): "Immediately after I indicate that I cleaned the bird cage, remind
-- me to refill the water". A follow-up waits on its task; each time that task is done (a
-- repeating one, every round), a task is made from it and nudged at once.
CREATE TABLE task_follow_ups (
    id INTEGER PRIMARY KEY,
    after_task INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES members (id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    steps TEXT NOT NULL DEFAULT '[]',  -- JSON list
    last_task INTEGER REFERENCES tasks (id) ON DELETE SET NULL,  -- the latest one made
    created_at TEXT NOT NULL
);
CREATE INDEX task_follow_ups_after ON task_follow_ups (after_task);
