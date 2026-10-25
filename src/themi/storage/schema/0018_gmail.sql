-- Gmail sync state per linked account.
ALTER TABLE linked_accounts ADD COLUMN history_id TEXT;       -- where incremental sync resumes
ALTER TABLE linked_accounts ADD COLUMN last_synced_at TEXT;
ALTER TABLE linked_accounts ADD COLUMN poll_after TEXT;       -- set after rate limits or errors
ALTER TABLE linked_accounts ADD COLUMN poll_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE linked_accounts ADD COLUMN alerted_at TEXT;       -- "link again" sent; cleared on relink

-- Mail Themi has seen. Deleted with the account (unlinking forgets its mail).
CREATE TABLE emails (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    gmail_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    message_id_header TEXT,                        -- RFC 822 Message-ID, for replies
    from_address TEXT NOT NULL,
    from_name TEXT NOT NULL DEFAULT '',
    to_addresses TEXT NOT NULL DEFAULT '[]',       -- JSON list
    subject TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',            -- plain text, HTML stripped, capped
    labels TEXT NOT NULL DEFAULT '[]',             -- JSON list of Gmail label ids
    attachments TEXT NOT NULL DEFAULT '[]',        -- JSON list of {filename, mime_type, size}
    received_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (account_id, gmail_id)
);
CREATE INDEX emails_account_received ON emails (account_id, received_at);

-- Replies already sent, by action, so a retried send never goes out twice.
CREATE TABLE email_sends (
    idempotency_key TEXT PRIMARY KEY,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    gmail_id TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
