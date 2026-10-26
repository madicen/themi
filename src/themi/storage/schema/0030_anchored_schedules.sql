-- Anchored chore schedules (F7). `repeat` holds a fixed-date schedule as JSON
-- (see themi.core.repeat): "every Tuesday at 6pm", "first Monday of the month".
-- Floating schedules stay in times_per_week. `missed`: roll on to the next date,
-- or catch up. `due_before_task`: due the day before another chore's round.
ALTER TABLE tasks ADD COLUMN repeat TEXT;
ALTER TABLE tasks ADD COLUMN missed TEXT NOT NULL DEFAULT 'roll' CHECK (missed IN ('roll', 'catch_up'));
ALTER TABLE tasks ADD COLUMN due_before_task INTEGER REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE task_runs ADD COLUMN missed INTEGER NOT NULL DEFAULT 0;
