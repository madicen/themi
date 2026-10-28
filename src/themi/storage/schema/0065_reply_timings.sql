-- P2a, ideas #51 and #55: why a reply took as long as it did. Each reply that went to the
-- model, kept for a week like ai_calls: its whole time, the outbox's part, and the "still
-- coming" note if one went. Each tool it ran, and ai_calls says which reply a call was for.
CREATE TABLE replies (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    outbox_seconds REAL NOT NULL DEFAULT 0,
    slow_notice TEXT
);
CREATE INDEX replies_started ON replies (started_at);

CREATE TABLE reply_tools (
    id INTEGER PRIMARY KEY,
    reply_id INTEGER NOT NULL REFERENCES replies (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    after_model INTEGER NOT NULL,  -- the model round that asked for it
    started_at TEXT NOT NULL,
    seconds REAL NOT NULL
);
CREATE INDEX reply_tools_reply ON reply_tools (reply_id);

ALTER TABLE ai_calls ADD COLUMN reply_id INTEGER;
CREATE INDEX ai_calls_reply ON ai_calls (reply_id);
