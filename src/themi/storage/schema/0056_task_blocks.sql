-- K5: time blocked on someone's calendar for a task. Its nudges wait for the block; the
-- block follows the event if it's moved on the calendar, and ends if it's deleted.
CREATE TABLE task_blocks (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    themi_event_id INTEGER NOT NULL REFERENCES themi_events(id) ON DELETE CASCADE,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    nudged INTEGER NOT NULL DEFAULT 0,   -- its nudge went when the block began
    asked INTEGER NOT NULL DEFAULT 0,    -- "done, or move it?" after it ended
    created_at TEXT NOT NULL,
    removed_at TEXT                      -- deleted on the calendar: nudging as before
);
CREATE INDEX task_blocks_task ON task_blocks (task_id, member_id);

-- When each linked account's calendars were last read (K1's reader), so a block missing
-- from a read made after it was created is known to be deleted, even on an empty calendar.
CREATE TABLE calendar_reads (
    account_id INTEGER PRIMARY KEY REFERENCES linked_accounts(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    read_at TEXT NOT NULL
);
