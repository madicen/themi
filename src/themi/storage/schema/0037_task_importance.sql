-- C2c: reminders follow how much a task matters, and grow more specific when overdue.
ALTER TABLE tasks ADD COLUMN importance TEXT NOT NULL DEFAULT 'normal'
    CHECK (importance IN ('low', 'normal', 'high'));
-- This round's overdue reminders so far, and the local day of the last one.
ALTER TABLE tasks ADD COLUMN overdue_reminders INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN overdue_reminded_on TEXT;
-- The end-of-day message, once per person per day.
CREATE TABLE day_end_sent (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (member_id, day)
);
