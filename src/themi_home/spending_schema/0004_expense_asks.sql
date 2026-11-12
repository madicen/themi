-- EX2b: what Themi asked about expense sheets. kind: 'ask' (one entry's empty key field,
-- on a personal sheet) or 'review' (a person's business entries, weekly; entry_id NULL,
-- week the ISO week it covers). status: queued, sent, answered, skipped, cancelled. A
-- skipped entry is never asked about again.
CREATE TABLE expense_asks (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    kind TEXT NOT NULL CHECK (kind IN ('ask', 'review')),
    entry_id INTEGER REFERENCES expense_entries (id),
    field_key TEXT NOT NULL DEFAULT '',
    week TEXT NOT NULL DEFAULT '',
    outbox_id INTEGER,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'answered', 'skipped', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX expense_asks_entry ON expense_asks (entry_id);
CREATE INDEX expense_asks_member ON expense_asks (member_id, kind, status);
