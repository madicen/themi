-- K3: events made and changed from chat, and suggested by booking emails.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('calendar_event', 'Add or change events on your own calendar', 'member', 2,
     '1970-01-01T00:00:00+00:00'),
    ('calendar_event_change', 'Change or delete an event Themi didn''t make', 'member', 1,
     '1970-01-01T00:00:00+00:00'),
    ('calendar_from_email', 'Add events from booking emails to your calendar', 'member', 2,
     '1970-01-01T00:00:00+00:00');

-- The events Themi made, so it knows them before the next read of the calendar and can
-- change them without asking. `source`: 'chat', or 'email:<email id>'.
CREATE TABLE themi_events (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    all_day INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    action_key TEXT UNIQUE,  -- the action that made it, so a retry doesn't make it twice
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
