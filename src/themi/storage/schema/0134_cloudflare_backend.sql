-- Cloudflare Workers AI as a backend kind, for step pictures (free daily allowance, no card).
-- ai_backends checks its kinds, so it's rebuilt. Dropping it would cascade to ai_routes (the
-- only table pointing at it), so the routes are kept aside and put back, ids unchanged.
CREATE TABLE ai_routes_keep AS SELECT * FROM ai_routes;
CREATE TABLE ai_backends_new (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN
        ('anthropic', 'gemini', 'ollama', 'lm_studio', 'openai_compat', 'cloudflare')),
    model TEXT NOT NULL DEFAULT '',               -- '' = the provider's default
    base_url TEXT,                                -- Cloudflare: the account ID
    api_key BLOB,                                 -- encrypted; NULL for local servers
    timeout REAL NOT NULL DEFAULT 60.0,
    supports_tools INTEGER NOT NULL DEFAULT 1,
    supports_structured INTEGER NOT NULL DEFAULT 1,
    supports_audio INTEGER NOT NULL DEFAULT 0,
    effort TEXT,                                  -- Claude only
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (member_id, label)
);
INSERT INTO ai_backends_new SELECT * FROM ai_backends;
DROP TABLE ai_backends;
ALTER TABLE ai_backends_new RENAME TO ai_backends;
INSERT INTO ai_routes SELECT * FROM ai_routes_keep;
DROP TABLE ai_routes_keep;
