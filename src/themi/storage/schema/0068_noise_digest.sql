-- F16b (ideas #61, #63, bug #66): emails that look like noise are offered for archiving
-- together, in one message, at a time each person chooses, instead of a card each.
-- noise_emails: 'daily' (6 pm), 'twice' (noon and 6 pm) or 'every_other_day' (6 pm).
ALTER TABLE members ADD COLUMN noise_emails TEXT NOT NULL DEFAULT 'daily'
    CHECK (noise_emails IN ('daily', 'twice', 'every_other_day'));

CREATE TABLE noise_digests (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    outbox_id INTEGER,
    action_ids TEXT NOT NULL,                     -- JSON: the offers it listed
    answer TEXT,                                  -- 'archived', 'later', or NULL
    created_at TEXT NOT NULL
);
CREATE INDEX noise_digests_member ON noise_digests (member_id, created_at);
