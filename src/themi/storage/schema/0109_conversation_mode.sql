-- CM1a: conversation mode. Each person can choose to talk with a plain chat model (no
-- tools) while a background pass picks out tasks and events (CM1b). Off by default.
ALTER TABLE members ADD COLUMN conversation_mode INTEGER NOT NULL DEFAULT 0;

-- Two new AI tasks, each with its own route: 'chat' (the reply in conversation mode) and
-- 'sidecar' (the background pass). ai_routes checks its task names, so it's rebuilt.
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding', 'chat', 'sidecar')),
    position INTEGER NOT NULL,                    -- 0 = primary, then fallbacks
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,                                   -- overrides the backend's model for this task
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;

-- Each person starts with what they use now: chat as their conversation chain, the
-- sidecar as their chain for other quick structured jobs.
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT member_id, 'chat', position, backend_id, model FROM ai_routes WHERE task = 'conversation';
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT member_id, 'sidecar', position, backend_id, model FROM ai_routes
WHERE task = 'structured_misc';
