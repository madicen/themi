-- E2b: the email audit asks how urgent and how important, each on a scale, in words.
-- urgency: 0 not urgent, 1 same day, 2 right away. importance: 0 not, 1 somewhat, 2 very.
-- `answer` stays, as the pair in short (urgent, important, both or neither).
ALTER TABLE email_audit_items ADD COLUMN urgency INTEGER;
ALTER TABLE email_audit_items ADD COLUMN importance INTEGER;
UPDATE email_audit_items
SET urgency = CASE WHEN answer IN ('urgent', 'both') THEN 1 ELSE 0 END,
    importance = CASE WHEN answer IN ('important', 'both') THEN 1 ELSE 0 END
WHERE answer IS NOT NULL;

-- A task that's Themi's own (the email audit) never goes on the wall's to-do lists; any
-- already there come off at the next sync.
ALTER TABLE tasks ADD COLUMN off_wall INTEGER NOT NULL DEFAULT 0;
UPDATE tasks SET off_wall = 1 WHERE id IN (SELECT task_id FROM email_audits);
UPDATE cozyla_links SET state = 'pending', version = version + 1, attempts = 0,
    retry_after = NULL
WHERE task_id IN (SELECT task_id FROM email_audits);
