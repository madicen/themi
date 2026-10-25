-- Background work that must survive restarts and AI outages: a job is
-- retried until it succeeds, re-queued (never dropped) when AI backends are
-- temporarily unavailable.
CREATE TABLE job_queue (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',          -- JSON
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    run_after TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,          -- failures, not counting deferrals
    deferrals INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    dedupe_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX job_queue_due ON job_queue (status, run_after);
CREATE UNIQUE INDEX job_queue_dedupe ON job_queue (dedupe_key) WHERE status IN ('queued', 'running');
