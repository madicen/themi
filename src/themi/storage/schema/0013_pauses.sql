-- "Pause meal reminders for today": a topic of proactive messages held until `until`.
CREATE TABLE pauses (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    until TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT                                  -- set when resumed early
);
CREATE INDEX pauses_member ON pauses (member_id, until);

-- Some messages (sign-in links) must go out without a link preview.
ALTER TABLE outbox ADD COLUMN link_preview INTEGER NOT NULL DEFAULT 1;
