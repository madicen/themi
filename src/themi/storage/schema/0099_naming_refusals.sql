-- P8a: each time a naming check refused a task tool ("nothing they said names Go for a
-- run"), and what came after: the same tool on the same task within ten minutes (the
-- refusal was wrong) or on another task (it was right). No message text.
CREATE TABLE naming_refusals (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    tool TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('not_named', 'names_other')),
    task_id INTEGER,
    refused_at TEXT NOT NULL,
    outcome TEXT CHECK (outcome IN ('wrong', 'right')),
    settled_at TEXT
);
CREATE INDEX naming_refusals_member ON naming_refusals (member_id, refused_at);
