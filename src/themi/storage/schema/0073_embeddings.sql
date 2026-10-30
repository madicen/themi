-- P7b: an embedding task for routing messages to tool groups, and a cache of vectors.
-- ai_routes checks its task names, so it's rebuilt to allow 'embedding'.
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding')),
    position INTEGER NOT NULL,                    -- 0 = primary, then fallbacks
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,                                   -- overrides the backend's model for this task
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;

-- Each member embeds on the Gemini backends of their conversation chain, in that order.
-- Only Gemini has an embeddings API here; without one, routing keeps to the word lists.
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT r.member_id, 'embedding', r.position, r.backend_id, 'gemini-embedding-2'
FROM ai_routes r JOIN ai_backends b ON b.id = r.backend_id
WHERE r.task = 'conversation' AND b.kind = 'gemini';

-- The group examples' vectors, so a restart doesn't embed them again. Messages aren't kept.
CREATE TABLE embedding_cache (
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,                         -- float32s, unit length
    PRIMARY KEY (model, text)
);
