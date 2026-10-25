-- Household rules. Ideas start as drafts and become standing rules only when
-- the person they affect locks them in.
CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    summary TEXT NOT NULL,                        -- one line, for people
    text TEXT NOT NULL,                           -- the rule as Themi follows it
    kind TEXT NOT NULL CHECK (kind IN ('policy', 'autonomy_grant', 'standing_reminder')),
    category TEXT REFERENCES action_categories(name),  -- for autonomy grants
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'locked', 'expired', 'discarded', 'unlocked')),
    proposed_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    affects INTEGER REFERENCES members(id) ON DELETE CASCADE,  -- who must lock it
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    locked_at TEXT,
    locked_by TEXT
);
CREATE INDEX rules_status ON rules (status);

-- The proposal messages for each rule, so locking can edit them.
CREATE TABLE rule_messages (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    outbox_id INTEGER NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
