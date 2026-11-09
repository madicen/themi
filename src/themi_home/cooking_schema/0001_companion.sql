-- CK1: the cooking companion, one migration for all of it (CK1 to CK8). The cook screen
-- and the chat card are two views of one session; `seq` bumps on every move from either.
ALTER TABLE cooking_sessions ADD COLUMN used TEXT NOT NULL DEFAULT '[]';        -- CK2: lines marked used
ALTER TABLE cooking_sessions ADD COLUMN ahead_done TEXT NOT NULL DEFAULT '{}';  -- CK4: look-ahead [Done] / [Later]
ALTER TABLE cooking_sessions ADD COLUMN energy_at_start TEXT;                   -- kept at start, as BD1a keeps it
ALTER TABLE cooking_sessions ADD COLUMN hour_of_week INTEGER;
ALTER TABLE cooking_sessions ADD COLUMN seq INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cooking_sessions ADD COLUMN step_since TEXT;                        -- CK5: on this step since
ALTER TABLE cooking_sessions ADD COLUMN stuck_said INTEGER NOT NULL DEFAULT 0;  -- CK5: the stuck line, once
ALTER TABLE cooking_sessions ADD COLUMN line TEXT NOT NULL DEFAULT '';          -- CK5: Themi's line on the screen
ALTER TABLE cooking_sessions ADD COLUMN line_at TEXT;
ALTER TABLE cooking_sessions ADD COLUMN page_at TEXT;                           -- the screen last asked for the state
ALTER TABLE cooking_sessions ADD COLUMN wrap TEXT NOT NULL DEFAULT '{}';        -- CK3/CK6: after the end, offers once

ALTER TABLE cooking_timers ADD COLUMN label TEXT;        -- CK3: "Sauce, step 3" or their own
ALTER TABLE cooking_timers ADD COLUMN cleared_at TEXT;   -- CK3: a fired timer tapped on the screen

-- CK2: which ingredient lines each step uses, from one model call, kept until the recipe's
-- words change.
CREATE TABLE cooking_links (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (recipe_id, hash)
);
