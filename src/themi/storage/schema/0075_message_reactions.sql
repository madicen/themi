-- S5: reactions on Themi's messages, by what kind of message and how long, so it learns
-- what lands with each person. One per message: a later reaction replaces the earlier.
CREATE TABLE message_reactions (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    outbox_id INTEGER NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                           -- nudges, check-ins, summaries, chat replies...
    length TEXT NOT NULL CHECK (length IN ('short', 'medium-length', 'long')),
    value INTEGER NOT NULL CHECK (value IN (-1, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (member_id, outbox_id)
);
