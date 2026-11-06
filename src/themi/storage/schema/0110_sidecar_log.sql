-- CM1b: what conversation mode's background pass (the sidecar) did after a chat reply.
-- One row per turn where it picked something out: the spec's SIDE_EFFECT_LOGGED event.
-- `items` is a JSON list of {tool, arguments, outcome, result}; `note` is the pass's own
-- few words on what it recorded. The person's message itself stays in message_log.
CREATE TABLE sidecar_log (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    telegram_message_id INTEGER,                  -- their message, which gets the ✍
    items TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'logged' CHECK (status IN ('logged', 'undone', 'missed')),
    created_at TEXT NOT NULL
);
CREATE INDEX sidecar_log_member ON sidecar_log (member_id, id);
