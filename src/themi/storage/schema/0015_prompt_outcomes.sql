-- Every message Themi started, and what came of it. Outcomes teach the energy
-- baseline when each person tends to have room for things.
CREATE TABLE prompt_outcomes (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    outbox_id INTEGER UNIQUE REFERENCES outbox(id) ON DELETE SET NULL,
    telegram_message_id INTEGER,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    hour_of_week INTEGER NOT NULL,
    respond_by TEXT NOT NULL,                      -- after this, silence means "ignored"
    outcome TEXT CHECK (outcome IN ('acted', 'snoozed', 'ignored')),
    resolved_at TEXT
);
CREATE INDEX prompt_outcomes_open ON prompt_outcomes (member_id, outcome);
