-- GK1: groceries said to Google Home land in Google Keep. Each person who links Keep (from
-- the command line) has a master token, kept encrypted, and the list to watch.
CREATE TABLE keep_accounts (
    member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    master_token BLOB NOT NULL,                   -- encrypted
    device_id TEXT NOT NULL,                      -- the id the token was made for
    list_name TEXT NOT NULL,
    linked_at TEXT NOT NULL
);

-- Each Keep item Themi has taken: 'added' (on the grocery list, not checked off in Keep
-- yet), 'checked' (done), or 'skipped' (no name Themi can keep; left in Keep).
CREATE TABLE keep_items (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('added', 'checked', 'skipped')),
    seen_at TEXT NOT NULL,
    PRIMARY KEY (member_id, item_id)
);
