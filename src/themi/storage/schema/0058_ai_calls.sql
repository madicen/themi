-- Bug #29: a reply took a minute and nothing said why. Each model call, kept for a week:
-- how long it took, how long it waited for a busy provider (Retry-After), and how it ended.
CREATE TABLE ai_calls (
    id INTEGER PRIMARY KEY,
    member_id INTEGER,
    task TEXT NOT NULL,
    kind TEXT NOT NULL,
    backend TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    seconds REAL NOT NULL,
    waited REAL NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    last_status INTEGER,
    ok INTEGER NOT NULL
);
CREATE INDEX ai_calls_started ON ai_calls (started_at);
