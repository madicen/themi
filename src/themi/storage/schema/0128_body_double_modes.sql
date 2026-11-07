-- BD2: which body double mode suits a job. A task's kind of job, set by its words or one
-- cheap call and kept (they can correct it); each person's own mode for a kind of job, which
-- always wins; and whether a session's mode was Themi's pick (said once, as an offer).
ALTER TABLE tasks ADD COLUMN category TEXT;
CREATE TABLE task_mode_preferences (
    member_id INTEGER NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ('deep_work', 'admin', 'chores', 'tidy', 'other')),
    mode TEXT NOT NULL CHECK (mode IN ('silent', 'sprint', 'guided')),
    PRIMARY KEY (member_id, category)
);
ALTER TABLE body_double_sessions ADD COLUMN mode_chosen INTEGER NOT NULL DEFAULT 0;
