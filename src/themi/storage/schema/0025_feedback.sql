-- Bug reports and ideas sent from the chat (/bug, /idea), each with a snapshot of
-- what was going on: the conversation, open items, settings and recent log lines.
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('bug', 'idea')),
    text TEXT NOT NULL,
    context TEXT NOT NULL,                         -- JSON snapshot
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewed')),
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX feedback_status ON feedback (status, created_at);
