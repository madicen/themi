-- 35a: meals someone ate (said in chat, a meal idea they picked, or a device), and the
-- reminders sent when it had been longer than their usual gap.
CREATE TABLE meals_eaten (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    eaten_at TEXT NOT NULL,
    what TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (source IN ('chat', 'suggestion', 'device')),
    created_at TEXT NOT NULL
);
CREATE INDEX meals_eaten_member ON meals_eaten (member_id, eaten_at);

CREATE TABLE meal_nudges (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL
);
CREATE INDEX meal_nudges_member ON meal_nudges (member_id, sent_at);
