-- Bug #9: a task can be a check-in ("did you go for a run?"), and its nudge says so.
ALTER TABLE tasks ADD COLUMN check_in INTEGER NOT NULL DEFAULT 0;
