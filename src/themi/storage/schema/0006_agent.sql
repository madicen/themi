-- Facts the agent was asked to remember. Prompt 14 replaces this with the
-- full memory store (pinning, search, context repair) and migrates rows over.
CREATE TABLE scratch_facts (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    fact TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Energy signals (explicit notes for now). Prompt 18 adds passive signals,
-- the per-hour baseline and the capacity model on top of this table.
CREATE TABLE energy_signals (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    source TEXT NOT NULL,                         -- text_note, message_timing, device_activity
    value REAL NOT NULL,                          -- -3 (draining) .. +3 (restoring)
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX energy_signals_member_time ON energy_signals (member_id, created_at);
