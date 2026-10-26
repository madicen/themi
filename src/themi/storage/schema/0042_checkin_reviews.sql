-- Idea #13: now and then, ask whether a check-in is helping.
ALTER TABLE habits ADD COLUMN check_ins INTEGER NOT NULL DEFAULT 0;  -- sent so far
ALTER TABLE members ADD COLUMN checkin_reviews INTEGER NOT NULL DEFAULT 1;  -- ask at all
CREATE TABLE checkin_reviews (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('habit', 'task')),
    ref_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    every INTEGER NOT NULL DEFAULT 4,      -- check-ins between asks
    seen INTEGER NOT NULL DEFAULT 0,       -- check-ins so far when last asked (or set up)
    yeses INTEGER NOT NULL DEFAULT 0,      -- "helpful" answers so far
    state TEXT NOT NULL DEFAULT 'on' CHECK (state IN ('on', 'off', 'done')),
    asked_at TEXT,                         -- waiting for an answer since
    UNIQUE (kind, ref_id)
);
