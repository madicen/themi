-- SL6: Themi writes the person's Slack status and Do Not Disturb from its own state, a
-- side effect like any other: automatic to start, and an admin can make it ask first.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('slack_status', 'Set your Slack status and Do Not Disturb', 'family', 2, 2,
     '1970-01-01T00:00:00+00:00');

-- The state Themi last wrote for each person: what it set (a status, Do Not Disturb) and
-- until when, so it changes Slack only when its own state changes, and clears only what
-- it set itself.
CREATE TABLE slack_status (
    member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    state TEXT NOT NULL,          -- focus, meeting, quiet, none
    until TEXT,                   -- when that state ends (UTC); none has no end
    set_status INTEGER NOT NULL DEFAULT 0,
    set_dnd INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
