-- EX1a: expense sheets. A book is one spreadsheet (a title, an owner or the household);
-- each sheet is one tab in it, with its own fields. Every value keeps its status, how sure
-- it is and where it came from. X1's `spending` rows move onto two built-in sheets: the
-- household's "Takeout & eating out" and each person's "Business". `spending` stays as a
-- read-only view for one release.

CREATE TABLE expense_books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    member_id INTEGER REFERENCES members (id),      -- NULL: the household's
    google_spreadsheet_id TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE expense_sheets (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES expense_books (id),
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('personal', 'business', 'custom')),
    member_id INTEGER REFERENCES members (id),      -- NULL: the household's
    prompt_on_missing_critical INTEGER NOT NULL DEFAULT 1,
    csv_enabled INTEGER NOT NULL DEFAULT 1,
    keywords TEXT NOT NULL DEFAULT '[]',            -- JSON list of words that route to it
    google_tab_id INTEGER,
    position INTEGER NOT NULL DEFAULT 0,             -- its place in its book
    counts_as_spending INTEGER NOT NULL DEFAULT 1,   -- mileage and income don't
    builtin TEXT CHECK (builtin IN ('takeout', 'business')),
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX expense_sheets_book ON expense_sheets (book_id, position);

CREATE TABLE expense_fields (
    id INTEGER PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES expense_sheets (id),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('money', 'date', 'text', 'choice', 'number')),
    choices TEXT NOT NULL DEFAULT '[]',              -- JSON list, for a choice
    critical INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (sheet_id, key)
);

-- origin: how the entry began (said in chat, or a receipt email); email_id: the receipt
-- attached to it, at most one entry per receipt (X1).
CREATE TABLE expense_entries (
    id INTEGER PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES expense_sheets (id),
    member_id INTEGER NOT NULL REFERENCES members (id),
    origin TEXT NOT NULL DEFAULT 'chat' CHECK (origin IN ('chat', 'email', 'website')),
    email_id INTEGER UNIQUE REFERENCES emails (id),
    created_at TEXT NOT NULL,
    removed_at TEXT
);
CREATE INDEX expense_entries_sheet ON expense_entries (sheet_id);

-- One row per entry and field; a change replaces it. value is JSON (cents for money,
-- YYYY-MM-DD for a date) or NULL: unknown, never made up.
CREATE TABLE expense_values (
    entry_id INTEGER NOT NULL REFERENCES expense_entries (id),
    field_id INTEGER NOT NULL REFERENCES expense_fields (id),
    value TEXT,
    status TEXT NOT NULL CHECK (status IN ('verified', 'unverified', 'user_estimate')),
    confidence REAL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'direct_user_input', 'email_receipt', 'calendar_event', 'chat_context', 'user_estimate'
    )),
    source_ref TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, field_id)
);

-- The household's built-in sheet, in a book of its own.
INSERT INTO expense_books (id, title, member_id, created_at)
    VALUES (1, 'Takeout & eating out', NULL, '1970-01-01T00:00:00+00:00');
INSERT INTO expense_sheets (id, book_id, title, mode, member_id, keywords, position, builtin,
                            created_at)
    VALUES (1, 1, 'Takeout & eating out', 'personal', NULL,
            '["takeout", "doordash", "restaurant", "dinner out", "eating out"]', 0, 'takeout',
            '1970-01-01T00:00:00+00:00');
INSERT INTO expense_fields (sheet_id, key, label, type, choices, critical, position) VALUES
    (1, 'amount', 'Amount', 'money', '[]', 1, 0),
    (1, 'date', 'Date', 'date', '[]', 1, 1),
    (1, 'vendor', 'Vendor', 'text', '[]', 0, 2),
    (1, 'category', 'Category', 'choice', '["takeout", "eating_out", "other"]', 0, 3),
    (1, 'note', 'Note', 'text', '[]', 0, 4);

-- Each person with business spends gets their Business book now; others get it when they
-- first need it.
INSERT INTO expense_books (title, member_id, created_at)
    SELECT 'Business', member_id, MIN(created_at) FROM spending WHERE business = 1
    GROUP BY member_id;
INSERT INTO expense_sheets (book_id, title, mode, member_id, keywords, position, builtin,
                            created_at)
    SELECT id, 'Business', 'business', member_id, '["for work", "business", "client"]', 0,
           'business', created_at
    FROM expense_books WHERE id > 1;
INSERT INTO expense_fields (sheet_id, key, label, type, choices, critical, position)
    SELECT s.id, f.key, f.label, f.type, f.choices, f.critical, f.position
    FROM expense_sheets s, (
        SELECT 'amount' AS key, 'Amount' AS label, 'money' AS type, '[]' AS choices,
               1 AS critical, 0 AS position
        UNION ALL SELECT 'date', 'Date', 'date', '[]', 1, 1
        UNION ALL SELECT 'vendor', 'Vendor', 'text', '[]', 1, 2
        UNION ALL SELECT 'category', 'Category', 'choice',
                         '["takeout", "eating_out", "other"]', 0, 3
        UNION ALL SELECT 'purpose', 'Business purpose', 'text', '[]', 1, 4
        UNION ALL SELECT 'attendees', 'Who was there', 'text', '[]', 0, 5
        UNION ALL SELECT 'note', 'Note', 'text', '[]', 0, 6
    ) f
    WHERE s.builtin = 'business';

-- Each spend becomes an entry with the same id, so "spend 3" still names it.
INSERT INTO expense_entries (id, sheet_id, member_id, origin, email_id, created_at)
    SELECT sp.id,
           CASE WHEN sp.business = 1 THEN (
               SELECT s.id FROM expense_sheets s
               WHERE s.builtin = 'business' AND s.member_id = sp.member_id
           ) ELSE 1 END,
           sp.member_id, sp.source, sp.email_id, sp.created_at
    FROM spending sp;

-- Said in chat: what they said (verified, it's theirs). From a receipt: Themi's reading
-- (unverified, 0.95), its lineage the Gmail message.
INSERT INTO expense_values (entry_id, field_id, value, status, confidence, source_type,
                            source_ref, evidence, recorded_at)
    SELECT sp.id, f.id,
           CASE f.key
               WHEN 'amount' THEN CAST(sp.amount_cents AS TEXT)
               WHEN 'date' THEN json_quote(sp.spent_on)
               WHEN 'vendor' THEN json_quote(sp.place)
               WHEN 'category' THEN json_quote(sp.kind)
               WHEN 'note' THEN json_quote(sp.note)
           END,
           CASE sp.source WHEN 'email' THEN 'unverified' ELSE 'verified' END,
           CASE sp.source WHEN 'email' THEN 0.95 ELSE 1.0 END,
           CASE sp.source WHEN 'email' THEN 'email_receipt' ELSE 'direct_user_input' END,
           CASE sp.source WHEN 'email' THEN COALESCE(
               (SELECT e.gmail_id FROM emails e WHERE e.id = sp.email_id), ''
           ) ELSE '' END,
           '',
           sp.created_at
    FROM spending sp
    JOIN expense_entries en ON en.id = sp.id
    JOIN expense_fields f ON f.sheet_id = en.sheet_id
    WHERE f.key IN ('amount', 'date', 'category')
       OR (f.key = 'vendor' AND sp.place != '')
       OR (f.key = 'note' AND sp.note != '');

DROP TABLE spending;

-- X1's table, read-only, for one release.
CREATE VIEW spending AS
SELECT en.id AS id,
       en.member_id AS member_id,
       (SELECT json_extract(v.value, '$') FROM expense_values v JOIN expense_fields f
            ON f.id = v.field_id WHERE v.entry_id = en.id AND f.key = 'amount') AS amount_cents,
       COALESCE((SELECT json_extract(v.value, '$') FROM expense_values v JOIN expense_fields f
            ON f.id = v.field_id WHERE v.entry_id = en.id AND f.key = 'vendor'), '') AS place,
       COALESCE((SELECT json_extract(v.value, '$') FROM expense_values v JOIN expense_fields f
            ON f.id = v.field_id WHERE v.entry_id = en.id AND f.key = 'category'), 'other')
            AS kind,
       CASE s.builtin WHEN 'business' THEN 1 ELSE 0 END AS business,
       COALESCE((SELECT json_extract(v.value, '$') FROM expense_values v JOIN expense_fields f
            ON f.id = v.field_id WHERE v.entry_id = en.id AND f.key = 'note'), '') AS note,
       (SELECT json_extract(v.value, '$') FROM expense_values v JOIN expense_fields f
            ON f.id = v.field_id WHERE v.entry_id = en.id AND f.key = 'date') AS spent_on,
       en.email_id AS email_id,
       en.origin AS source,
       en.created_at AS created_at
FROM expense_entries en JOIN expense_sheets s ON s.id = en.sheet_id
WHERE s.builtin IS NOT NULL AND en.removed_at IS NULL;
