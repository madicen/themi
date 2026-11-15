-- OV3: what Themi tells about the oven, and the trust tiers its writes go through.

-- One row per time an oven is on, from on to off: who started it through Themi (NULL: at
-- the range), the cook session it's for, and what's been told about it, once each.
CREATE TABLE oven_heatups (
    id INTEGER PRIMARY KEY,
    oven_id INTEGER NOT NULL REFERENCES ovens(id) ON DELETE CASCADE,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    session_id INTEGER,                           -- cooking_sessions.id (OV4)
    mode INTEGER NOT NULL,
    set_f INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    preheated_at TEXT,
    probe_near_at TEXT,
    probe_done_at TEXT,
    warned_at TEXT,                               -- left on: told
    fine_at TEXT                                  -- left on: [It's fine]
);
CREATE INDEX oven_heatups_open ON oven_heatups (oven_id, ended_at);

-- The oven's kitchen timer as Themi set it, and the cook-screen timer it goes with (OV5).
CREATE TABLE oven_timers (
    id INTEGER PRIMARY KEY,
    oven_id INTEGER NOT NULL REFERENCES ovens(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    minutes INTEGER NOT NULL,
    cooking_timer_id INTEGER,                     -- cooking_timers.id
    set_at TEXT NOT NULL,
    done_at TEXT
);

-- Heat is never automatic (max tier 1); the oven's timer may become so; off is automatic
-- from the start, so it never waits on anyone.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('oven_heat', 'Preheat the oven, proof dough or change its temperature', 'family', 1, 1,
     '1970-01-01T00:00:00+00:00'),
    ('oven_timer', 'Set the oven''s kitchen timer', 'family', 1, 2,
     '1970-01-01T00:00:00+00:00'),
    ('oven_off', 'Turn an oven off', 'family', 2, 2, '1970-01-01T00:00:00+00:00');
