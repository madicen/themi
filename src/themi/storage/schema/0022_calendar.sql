-- The scopes Google granted each linked account (JSON list), so Themi knows
-- whether an account can hold the family calendar.
ALTER TABLE linked_accounts ADD COLUMN scopes TEXT NOT NULL DEFAULT '[]';

-- Where Themi writes events: a calendar on an admin's linked account. With no
-- account chosen, the first admin's first linked account that allows it is used.
ALTER TABLE family ADD COLUMN calendar_account_id INTEGER
    REFERENCES linked_accounts(id) ON DELETE SET NULL;
ALTER TABLE family ADD COLUMN calendar_name TEXT NOT NULL DEFAULT 'Themi';

-- One Google Calendar event per thing Themi put on the calendar. The event id
-- is deterministic, so writing it again updates rather than duplicates.
CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('task')),   -- maintenance joins in prompt 33
    source_id INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    calendar_id TEXT,                              -- where it was written
    state TEXT NOT NULL DEFAULT 'approved' CHECK (state IN ('approved', 'synced', 'deleted')),
    synced_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);

-- Calendars found or made, per account and name, so they're looked up once.
CREATE TABLE calendars (
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    created_by_themi INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, name)
);
