-- Everything Themi sends a person, sent or waiting. The text is stored as
-- written; PDA shielding is applied at the moment it actually goes out.
CREATE TABLE outbox (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    buttons TEXT NOT NULL DEFAULT '[]',          -- JSON list of {label, kind, payload}
    priority TEXT NOT NULL CHECK (priority IN ('reply', 'urgent', 'normal', 'low')),
    kind TEXT NOT NULL DEFAULT 'chat',
    dedupe_key TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed')),
    send_after TEXT NOT NULL,
    deadline TEXT,                                -- send by then even if not a good window
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    sent_text TEXT,                               -- what actually went out, after shielding
    telegram_message_id INTEGER,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE INDEX outbox_due ON outbox (status, send_after);
CREATE INDEX outbox_dedupe ON outbox (member_id, dedupe_key);

-- Every change to a member's PDA strictness, and why.
CREATE TABLE pda_calibration_log (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    old_strength INTEGER NOT NULL,
    new_strength INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
