-- B1 (Erin's idea #42): a break holds task nudges and check-ins until it ends, then asks
-- "End break" or "Extend by N minutes"; N is each person's own.
ALTER TABLE members ADD COLUMN break_extend_minutes INTEGER NOT NULL DEFAULT 15;
CREATE TABLE breaks (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    pause_id INTEGER NOT NULL REFERENCES pauses (id),
    started_at TEXT NOT NULL,
    until TEXT NOT NULL,
    ended_at TEXT,
    end_outbox_id INTEGER
);
CREATE INDEX breaks_member ON breaks (member_id, ended_at);
