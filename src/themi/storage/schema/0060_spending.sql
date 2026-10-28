-- X1 (bug #36, idea #37): money spent, said in chat or found in a takeout receipt email.
-- kind: takeout, eating_out or other; business: a work expense, for the monthly export.
CREATE TABLE spending (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    place TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL CHECK (kind IN ('takeout', 'eating_out', 'other')),
    business INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    spent_on TEXT NOT NULL,
    email_id INTEGER UNIQUE REFERENCES emails (id),
    source TEXT NOT NULL CHECK (source IN ('chat', 'email')),
    created_at TEXT NOT NULL
);
CREATE INDEX spending_month ON spending (spent_on);
