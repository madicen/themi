-- BD4a: pictures from a model. A new AI task, `step_image`, with its own route (each
-- person starts with their quick-jobs chain, Gemini's image model in place of its chat
-- model), and each person's cap on pictures a day (the AI page), counted in ai_calls.
ALTER TABLE members ADD COLUMN image_daily_cap INTEGER NOT NULL DEFAULT 12;
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding', 'chat', 'sidecar', 'recipes', 'body_double_steps', 'step_image')),
    position INTEGER NOT NULL,
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT r.member_id, 'step_image', r.position, r.backend_id,
       CASE b.kind WHEN 'gemini' THEN 'gemini-3.1-flash-lite-image'
                   WHEN 'openai_compat' THEN 'gpt-image-2' ELSE r.model END
FROM ai_routes r JOIN ai_backends b ON b.id = r.backend_id
WHERE r.task = 'structured_misc';
