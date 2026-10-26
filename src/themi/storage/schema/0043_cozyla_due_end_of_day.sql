-- To-dos were sent due at midnight, so the wall showed them overdue all day. They're now
-- due at the end of their day (or at the task's own time); send the ones already there again.
UPDATE cozyla_links SET state = 'pending', version = version + 1, attempts = 0, retry_after = NULL
WHERE todo_id IS NOT NULL AND task_id IN (
    SELECT id FROM tasks WHERE due_on IS NOT NULL AND status IN ('open', 'snoozed')
    AND times_per_week IS NULL AND repeat IS NULL AND due_before_task IS NULL AND on_chart = 0
);
