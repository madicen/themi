-- F19c (Erin's idea #86): a task on both lists, put off by one of them, is put off for that
-- person alone; the other still has it.
CREATE TABLE task_snoozes (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    until TEXT NOT NULL,
    PRIMARY KEY (task_id, member_id)
);
CREATE INDEX task_snoozes_until ON task_snoozes (until);
