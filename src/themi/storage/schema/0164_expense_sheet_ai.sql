-- EX1b: a new AI task, `expense_sheet_fields` (the fields a new expense sheet has), with its
-- own route on the AI page. Each person starts with their quick-jobs chain.
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding', 'chat', 'sidecar', 'recipes', 'body_double_steps', 'step_image',
         'expense_sheet_fields')),
    position INTEGER NOT NULL,
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT member_id, 'expense_sheet_fields', position, backend_id, model FROM ai_routes
WHERE task = 'structured_misc';
