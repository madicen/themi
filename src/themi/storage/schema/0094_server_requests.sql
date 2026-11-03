-- D3a: updates and restarts asked for on the website. Themi writes the request to a folder
-- shared with the host; the host's runner (D3b) does the work and writes the result back.
-- `state`: waiting (written, not picked up yet), running, done, failed, refused (the runner
-- wouldn't), lapsed (nothing picked it up in time). `detail`: the end of the runner's output.
CREATE TABLE server_requests (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN ('update', 'restart')),
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    action_id INTEGER,                            -- the staged action that wrote it
    state TEXT NOT NULL
        CHECK (state IN ('waiting', 'running', 'done', 'failed', 'refused', 'lapsed')),
    from_version TEXT,
    to_version TEXT,
    detail TEXT,
    asked_at TEXT NOT NULL,
    finished_at TEXT,
    reported_at TEXT
);
CREATE UNIQUE INDEX server_requests_action ON server_requests (action_id);

INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('server_control', 'Update or restart Themi''s server', 'family', 2,
     '1970-01-01T00:00:00+00:00');
