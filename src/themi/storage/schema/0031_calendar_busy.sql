-- Busy blocks from each person's primary Google calendar (S2): only when, never
-- what. They hold Themi's messages like busy times and feed the energy estimate.
CREATE TABLE calendar_busy (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX calendar_busy_member ON calendar_busy (member_id, starts_at);
