-- E1 (Erin's idea #27): senders Themi suggested as "always urgent", so each is offered once;
-- `added` is set when the person tapped it.
CREATE TABLE sender_suggestions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    address TEXT NOT NULL,
    label TEXT NOT NULL,
    offered_at TEXT NOT NULL,
    added_at TEXT,
    UNIQUE (account_id, address)
);
