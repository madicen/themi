-- K1: each person's own calendars, read with their details. Asked for on 2026-10-26; the
-- plan's "only when, never what" for calendars changed with it.

-- Who sees a person's event details: just them ('me'), or the partner too ('partner').
ALTER TABLE members ADD COLUMN calendar_details TEXT NOT NULL DEFAULT 'me'
    CHECK (calendar_details IN ('me', 'partner'));

-- The calendars Themi reads for a linked account (none chosen: the primary one).
CREATE TABLE member_calendars (
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (account_id, calendar_id)
);

-- Their events for the next two weeks, as of the last read: title, place and times only,
-- never descriptions or attendees. `source` is set for events Themi made ("task:12").
CREATE TABLE calendar_entries (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    all_day INTEGER NOT NULL DEFAULT 0,
    video INTEGER NOT NULL DEFAULT 0,
    busy INTEGER NOT NULL DEFAULT 1,
    source TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX calendar_entries_member ON calendar_entries (member_id, starts_at);
