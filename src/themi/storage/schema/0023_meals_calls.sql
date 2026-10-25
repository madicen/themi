-- Meal ideas Themi offered (two at a time), and which one was picked.
CREATE TABLE meal_suggestions (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    options TEXT NOT NULL,                         -- JSON list of {title, uses, steps, minutes}
    chosen INTEGER,                                -- index into options
    created_at TEXT NOT NULL,
    chosen_at TEXT
);

-- Scripts for calls a person makes to a vendor, delivered with the call task,
-- and what they said happened afterwards.
CREATE TABLE call_scripts (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    vendor TEXT NOT NULL,
    objective TEXT NOT NULL,
    script TEXT NOT NULL,                          -- JSON: opening, questions, outcomes, fallback
    outcome TEXT,
    outcome_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    outcome_at TEXT,
    created_at TEXT NOT NULL
);
