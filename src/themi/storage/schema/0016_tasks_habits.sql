-- Who usually takes each kind of task (kind -> member id), and how much "room"
-- a hand-over costs before it's worth passing a task to the other partner.
ALTER TABLE family ADD COLUMN task_owners TEXT NOT NULL DEFAULT '{}';
ALTER TABLE family ADD COLUMN handover_cost REAL NOT NULL DEFAULT 10;
-- How costly each kind of task is for this person (kind -> multiplier, 1 = neutral).
ALTER TABLE members ADD COLUMN kind_costs TEXT NOT NULL DEFAULT '{}';

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('text', 'call', 'physical', 'errand')),
    effort INTEGER NOT NULL CHECK (effort BETWEEN 1 AND 5),
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    default_owner INTEGER REFERENCES members(id) ON DELETE SET NULL,
    assignee INTEGER REFERENCES members(id) ON DELETE SET NULL,
    assign_reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'snoozed', 'done', 'cancelled')),
    due_on TEXT,                                   -- local date, YYYY-MM-DD
    snoozed_until TEXT,
    prompt_outbox_id INTEGER REFERENCES outbox(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX tasks_assignee_status ON tasks (assignee, status);

-- Possible new check-ins, held in reserve and offered only when they'd likely help.
CREATE TABLE habits (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    idea TEXT NOT NULL,                            -- what the check-in is, for the offer
    prompt TEXT NOT NULL,                          -- what gets sent once it's active
    status TEXT NOT NULL DEFAULT 'reserve'
        CHECK (status IN ('reserve', 'offered', 'active', 'declined', 'retired')),
    action_id INTEGER REFERENCES pending_actions(id) ON DELETE SET NULL,
    offered_at TEXT,
    last_sent_on TEXT,                             -- local date
    last_outbox_id INTEGER,
    ignored_streak INTEGER NOT NULL DEFAULT 0,
    UNIQUE (member_id, idea)
);
