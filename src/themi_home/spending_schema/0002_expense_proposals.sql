-- EX1b: a sheet (or a book's tabs) proposed in chat, shown first with [Make it] and
-- [Change it]. phase: proposing (the card is up), changing (their next message says how),
-- made or dropped. proposal is the JSON shown; book_id is the book they named, if any.
CREATE TABLE expense_proposals (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    request TEXT NOT NULL,
    book_id INTEGER REFERENCES expense_books (id),
    proposal TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'proposing'
        CHECK (phase IN ('proposing', 'changing', 'made', 'dropped')),
    outbox_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
