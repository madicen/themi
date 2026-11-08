-- F26c (idea #142): a task's steps split into tasks of their own. Each part is a task;
-- this says whose part it is. A parent with parts is off every list and display (its
-- parts stand in for it) until the last part is settled, when it's checked off.
CREATE TABLE task_parts (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    parent_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL
);
CREATE INDEX task_parts_parent ON task_parts (parent_id);
