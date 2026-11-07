-- BD1b: Guided Step-Through. The session's own copy of its steps (the task's, or proposed
-- ones, which go on the task only when they say so), where it's up to, and its card.
ALTER TABLE body_double_sessions ADD COLUMN steps TEXT NOT NULL DEFAULT '[]';
ALTER TABLE body_double_sessions ADD COLUMN step INTEGER NOT NULL DEFAULT 0;
ALTER TABLE body_double_sessions ADD COLUMN step_since TEXT;
ALTER TABLE body_double_sessions ADD COLUMN steps_proposed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE body_double_sessions ADD COLUMN nudged INTEGER NOT NULL DEFAULT 0;
-- the chat message that shows the session (its start, or the guided card), for edits
ALTER TABLE body_double_sessions ADD COLUMN card_message_id INTEGER;

-- A new AI task with its own route: proposing a guided session's steps. ai_routes checks its
-- task names, so it's rebuilt; each person starts with their chain for other quick
-- structured jobs.
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding', 'chat', 'sidecar', 'recipes', 'body_double_steps')),
    position INTEGER NOT NULL,
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT member_id, 'body_double_steps', position, backend_id, model FROM ai_routes
WHERE task = 'structured_misc';
