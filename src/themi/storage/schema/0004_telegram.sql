-- Inline-keyboard buttons. Telegram only carries the opaque token back;
-- what a tap means lives here, so a client can't forge a payload.
CREATE TABLE callback_tokens (
    token TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,                       -- all buttons of one keyboard
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,                           -- what the tap is about, e.g. 'approval'
    payload TEXT NOT NULL DEFAULT '{}',           -- JSON
    message_id INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX callback_tokens_group ON callback_tokens (group_id);
