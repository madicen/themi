-- Bug #14: a task can be due at a time of day ("today around 2"); its nudge waits for it.
ALTER TABLE tasks ADD COLUMN due_time TEXT;  -- HH:MM, local
