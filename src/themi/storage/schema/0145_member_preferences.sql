-- CR7a: each member's settings that belong to one module, one row per setting, the
-- value as JSON. The body double's, a break's and the chore chart's move here from
-- `members`, whose columns stay (unused) until CR7b drops them.
CREATE TABLE member_preferences (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (member_id, module, key)
);

INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'body_double', 'sprint_work_minutes', json(sprint_work_minutes), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'body_double', 'sprint_break_minutes', json(sprint_break_minutes), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'body_double', 'body_double_sound', json_quote(body_double_sound), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'body_double', 'body_double_volume', json(body_double_volume), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'breaks', 'break_extend_minutes', json(break_extend_minutes), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'cozyla_chores', 'chart_limit', json(chart_limit), datetime('now')
FROM members;
INSERT INTO member_preferences (member_id, module, key, value, updated_at)
SELECT id, 'cozyla_chores', 'chart_counts_shared',
       CASE WHEN chart_counts_shared THEN 'true' ELSE 'false' END, datetime('now')
FROM members;
