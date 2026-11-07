-- F34f (idea #175): a calendar of theirs shown on the family calendar, at a level of detail
-- they chose: full (title and place), title, label (by kind: a meeting, a focus block,
-- anything else) or busy. `status` is 'waiting' until its yes (one `calendar_write` action),
-- then 'on'.
CREATE TABLE calendar_shown_on (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('full', 'title', 'label', 'busy')),
    status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'on')),
    action_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (account_id, calendar_id)
);

-- Each copy Themi keeps, by its source event. `hash` is what was last written, so a copy is
-- written again only when its source changed.
CREATE TABLE calendar_copies (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES calendar_shown_on(id) ON DELETE CASCADE,
    source_event_id TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    calendar_id TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL,
    hash TEXT NOT NULL DEFAULT '',
    UNIQUE (rule_id, source_event_id)
);

-- The labels a "label" rule uses, as JSON {"meeting", "focus", "other"}; NULL: the usual
-- ("Michael work meeting", "Michael focus block", "Michael busy").
ALTER TABLE members ADD COLUMN calendar_labels TEXT;
