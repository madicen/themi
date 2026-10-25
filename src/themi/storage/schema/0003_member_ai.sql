-- AI backends each member has set up (a provider, its key, and defaults).
CREATE TABLE ai_backends (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('anthropic', 'gemini', 'ollama', 'lm_studio', 'openai_compat')),
    model TEXT NOT NULL DEFAULT '',               -- '' = the provider's default
    base_url TEXT,
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

-- Which backends handle each AI task for a member, tried in `position` order.
CREATE TABLE ai_routes (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription')),
    position INTEGER NOT NULL,                    -- 0 = primary, then fallbacks
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,                                   -- overrides the backend's model for this task
    PRIMARY KEY (member_id, task, position)
);
