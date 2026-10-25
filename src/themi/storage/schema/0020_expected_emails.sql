-- Recurring emails someone expects (a bill confirmation each month, say). When
-- one is overdue past its grace period, Themi alerts and escalates `category`.
CREATE TABLE expected_emails (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                            -- "the PG&E confirmation"
    sender_pattern TEXT NOT NULL,                  -- an address, or @domain
    subject_pattern TEXT NOT NULL DEFAULT '',      -- case-insensitive substring; '' is any
    cadence_days INTEGER NOT NULL CHECK (cadence_days BETWEEN 1 AND 400),
    grace_days INTEGER NOT NULL CHECK (grace_days BETWEEN 0 AND 60),
    category TEXT NOT NULL REFERENCES action_categories(name),
    known_senders TEXT NOT NULL DEFAULT '[]',      -- JSON list of addresses seen for it
    last_seen_at TEXT,
    last_alerted_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (account_id, name)
);

-- Amounts parsed from confirmations, so an unusually large one stands out.
ALTER TABLE emails ADD COLUMN amount_cents INTEGER;
