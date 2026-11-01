-- T2: a chore that waits for another. A deadline chore (`due_before_task`) can also hold its
-- target back: the target's round isn't raised until this one is done for it. `hold_once`
-- ("next time"): the hold, and this chore, end after it's done once.
ALTER TABLE tasks ADD COLUMN holds_target INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN hold_once INTEGER NOT NULL DEFAULT 0;
-- A round that came up late (its hold ended after its day) runs until the day before the
-- next round, rather than ending on its own date.
ALTER TABLE tasks ADD COLUMN round_until TEXT;
