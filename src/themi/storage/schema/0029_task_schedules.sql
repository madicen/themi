-- Repeating chores (F6b). A schedule: target times a week, a minimum (at least
-- every N days) and an escalation point (after N days: to the owner again, or
-- shared with both partners). Each "done" is a run.
ALTER TABLE tasks ADD COLUMN times_per_week REAL;
ALTER TABLE tasks ADD COLUMN minimum_days REAL;
ALTER TABLE tasks ADD COLUMN escalate_days REAL;
ALTER TABLE tasks ADD COLUMN escalate_to TEXT CHECK (escalate_to IN ('owner', 'both'));
ALTER TABLE tasks ADD COLUMN shared INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN overdue_notified_at TEXT;
ALTER TABLE tasks ADD COLUMN escalated_at TEXT;
ALTER TABLE tasks ADD COLUMN step_up_offered_at TEXT;

CREATE TABLE task_runs (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    done_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    done_at TEXT NOT NULL,
    due_on TEXT,                                   -- what it was due by, if anything
    on_time INTEGER NOT NULL,
    notes TEXT
);
CREATE INDEX task_runs_task ON task_runs (task_id, done_at);

-- Offering to do a chore more often. Themi never changes a schedule on its own.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('chore_step_up', 'Try a chore more often', 'member', 1, '1970-01-01T00:00:00+00:00');
