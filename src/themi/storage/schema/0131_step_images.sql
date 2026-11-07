-- BD4b: a picture for each step of a guided session. The files live under data/step_images/
-- (never committed); a task's saved steps keep their pictures for next time (matched by the
-- task and the step's words).
CREATE TABLE step_images (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES body_double_sessions (id),
    member_id INTEGER NOT NULL REFERENCES members (id),
    task_id INTEGER REFERENCES tasks (id),
    step_index INTEGER NOT NULL,
    step_text TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    file TEXT,                        -- the file's name in data/step_images/
    mime_type TEXT,
    status TEXT NOT NULL,             -- ready, failed or capped
    made_at TEXT NOT NULL,
    UNIQUE (session_id, step_index)
);
CREATE INDEX step_images_task ON step_images (task_id, step_text);
