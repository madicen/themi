-- SL1: Slack names a message by its conversation and a `ts` string; the outbox and the
-- message log keep integers. Each Slack message Themi sends or sees gets one here.
CREATE TABLE slack_messages (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    ts TEXT NOT NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (channel, ts)
);

-- Each member's DM with the Themi app (conversations.open, once).
CREATE TABLE slack_dm_channels (
    member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL
);
