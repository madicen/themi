-- CR7b1: the rest of the members' settings that belong to one module move to
-- member_preferences. The `members` columns stay, unused, until CR7c drops them.
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'focus', 'focus_count', json(focus_count), datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'focus', 'day_budget', json(day_budget), datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'tasks', 'done_praise', CASE WHEN done_praise THEN 'true' ELSE 'false' END,
       datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'checkin_reviews', 'checkin_reviews',
       CASE WHEN checkin_reviews THEN 'true' ELSE 'false' END, datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'calendar', 'calendar_details', json_quote(calendar_details), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'calendar', 'calendar_twins', json_quote(calendar_twins), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'calendar', 'setup_note', CASE WHEN setup_note THEN 'true' ELSE 'false' END,
       datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'day_summary', 'morning_summary', json_quote(morning_summary), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'day_summary', 'morning_summary_empty',
       CASE WHEN morning_summary_empty THEN 'true' ELSE 'false' END, datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'travel', 'getting_ready_minutes', json(getting_ready_minutes), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'travel', 'leave_heads_up', CASE WHEN leave_heads_up THEN 'true' ELSE 'false' END,
       datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'gmail', 'noise_emails', json_quote(noise_emails), datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'conversation_mode', 'conversation_mode',
       CASE WHEN conversation_mode THEN 'true' ELSE 'false' END, datetime('now') FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'lists', 'list_style', json_quote(list_style), datetime('now') FROM members;
