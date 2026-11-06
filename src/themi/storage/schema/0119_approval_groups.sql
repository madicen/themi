-- F26b (idea #137): approvals from one email thread, or one sender within a few minutes,
-- asked about in one message. `alone_email`: an email triage rated urgent or important,
-- whose approvals don't join anyone else's message.
CREATE TABLE approval_groups (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,                     -- the from address, lower case
    sender_name TEXT NOT NULL,
    alone_email INTEGER,
    outbox_id INTEGER REFERENCES outbox(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    last_at TEXT NOT NULL,                    -- when an approval last joined it
    shown TEXT,                               -- the text and buttons last shown
    closed_at TEXT                            -- answered, or sent on one by one
);
CREATE INDEX approval_groups_open ON approval_groups (member_id, closed_at);

CREATE TABLE approval_group_items (
    group_id INTEGER NOT NULL REFERENCES approval_groups(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES pending_actions(id) ON DELETE CASCADE,
    email_id INTEGER NOT NULL,
    note TEXT,                                -- why Themi withdrew it, when it did
    PRIMARY KEY (group_id, action_id)
);
CREATE INDEX approval_group_items_action ON approval_group_items (action_id);
