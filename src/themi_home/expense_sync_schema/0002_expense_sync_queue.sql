-- EX4b: which Google account and spreadsheet copies each book, who it's for (their trust
-- category), and what was said about it once (deleted in Google; a day of failures).
CREATE TABLE expense_book_links (
    book_id INTEGER PRIMARY KEY REFERENCES expense_books (id),
    member_id INTEGER NOT NULL REFERENCES members (id),
    account_id INTEGER NOT NULL REFERENCES linked_accounts (id) ON DELETE CASCADE,
    made_at TEXT NOT NULL,
    failing_told_at TEXT
);

-- The sync queue: an entry (or 0: the sheet itself, its tab and header) to write again.
-- Filled when an entry or value changes, drained every few minutes through the trust tiers.
CREATE TABLE expense_sync (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    sheet_id INTEGER NOT NULL REFERENCES expense_sheets (id),
    wanted_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE INDEX expense_sync_waiting ON expense_sync (sheet_id, done_at);
