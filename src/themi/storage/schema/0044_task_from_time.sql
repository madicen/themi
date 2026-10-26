-- A time window ("between 2 and 3"): the nudge comes at its start, and it's due at its end.
ALTER TABLE tasks ADD COLUMN from_time TEXT;  -- HH:MM, local
