-- RC3a: cooking a recipe with Themi, one session per person, on one card edited in place.
CREATE TABLE cooking_sessions (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    scale REAL NOT NULL DEFAULT 1.0,
    scale_said TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL CHECK (phase IN ('ready', 'gather', 'prep', 'cook', 'done')),
    step INTEGER NOT NULL DEFAULT 0,      -- RC3b: the step on the card, from 0
    message_id INTEGER,                   -- the card's Telegram message
    in_group INTEGER NOT NULL DEFAULT 0,  -- started in the family group: either partner taps
    gathered TEXT NOT NULL DEFAULT '[]',  -- ingredient lines ticked as they're out
    prep TEXT NOT NULL DEFAULT '[]',      -- the prep jobs shown
    ahead TEXT NOT NULL DEFAULT '[]',     -- what needed time first
    started_at TEXT NOT NULL,
    last_tap_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT CHECK (outcome IN ('finished', 'stopped', 'left', 'switched'))
);
CREATE INDEX cooking_sessions_open ON cooking_sessions (member_id, ended_at);

-- The prep jobs read from a recipe, kept until its words change.
CREATE TABLE recipe_prep (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (recipe_id, hash)
);
