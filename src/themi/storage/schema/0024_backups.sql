-- Each backup attempt, so the nightly job knows when the last good one was.
CREATE TABLE backup_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
    snapshot TEXT,                                 -- the object key, when it worked
    size INTEGER,
    pruned INTEGER NOT NULL DEFAULT 0,             -- old snapshots deleted afterwards
    error TEXT
);
CREATE INDEX backup_runs_status ON backup_runs (status, started_at);
