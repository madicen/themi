-- The Telegram message that asked about each action, so the answer can be
-- shown by editing it. The message id lives on the outbox row once it's sent.
CREATE TABLE approval_messages (
    id INTEGER PRIMARY KEY,
    action_id INTEGER NOT NULL REFERENCES pending_actions(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    outbox_id INTEGER NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE INDEX approval_messages_action ON approval_messages (action_id);
