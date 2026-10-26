-- C1b: Themi's one-off tasks and a Cozyla to-do list, kept in step both ways.
-- A link per task: its to-do on the wall once made, and whether Themi has a
-- change still to send. `version` grows with every change, so one made while
-- the sync is sending isn't marked sent by mistake.
CREATE TABLE cozyla_links (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    todo_id TEXT UNIQUE,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'done')),
    version INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    retry_after TEXT,
    error TEXT
);
CREATE INDEX cozyla_links_state ON cozyla_links (state, retry_after);

-- The list as it was at the last sync, so the next can tell what changed on the wall.
-- Kept per list: a newly configured list starts with a first import.
CREATE TABLE cozyla_seen (
    list_id TEXT NOT NULL,
    todo_id TEXT NOT NULL,
    title TEXT NOT NULL,
    assignee TEXT,
    due_on TEXT,
    completed INTEGER NOT NULL,
    PRIMARY KEY (list_id, todo_id)
);
CREATE TABLE cozyla_sync (
    list_id TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL
);
