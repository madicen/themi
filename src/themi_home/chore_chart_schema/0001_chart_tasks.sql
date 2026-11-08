-- CR21a: the one-offs someone put on the chore chart (repeating chores are always on it),
-- in place of tasks.on_chart, which is left as it was and no longer read.
CREATE TABLE chart_tasks (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL
);
INSERT INTO chart_tasks (task_id, added_at) SELECT id, created_at FROM tasks WHERE on_chart = 1;
