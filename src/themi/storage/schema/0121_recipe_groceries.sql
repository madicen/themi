-- RC2a: what a recipe needs, onto the grocery list.
-- Each ingredient line read as a shopping item by the model, kept by the line's text so it's
-- never asked twice (a rule-based reading isn't kept: the model may do better next time).
CREATE TABLE recipe_ingredient_lines (
    key TEXT PRIMARY KEY,   -- a hash of the line, spaces and case evened out
    data TEXT NOT NULL,     -- JSON: line, item, quantity, unit, note, optional, staple
    created_at TEXT NOT NULL
);

-- A grocery card: the items one or more recipes need, each ticked or not, until Add.
CREATE TABLE recipe_cards (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    recipe_ids TEXT NOT NULL,           -- JSON list
    rows TEXT NOT NULL,                 -- JSON [{name, ticked, why, recipes, lines}]
    offers TEXT NOT NULL DEFAULT '[]',  -- cookbook recipes an ingredient names (Bechamel Sauce)
    scale REAL NOT NULL DEFAULT 1.0,    -- RC2b
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'added', 'closed', 'merged')),
    created_at TEXT NOT NULL
);

-- A new AI task with its own route: reading recipes (ingredient lines here; prep in RC3a and
-- recipe pages in RC4a). ai_routes checks its task names, so it's rebuilt; each person starts
-- with their chain for other quick structured jobs.
CREATE TABLE ai_routes_new (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task TEXT NOT NULL CHECK (task IN
        ('conversation', 'pda_rewrite', 'email_triage', 'structured_misc', 'transcription',
         'embedding', 'chat', 'sidecar', 'recipes')),
    position INTEGER NOT NULL,
    backend_id INTEGER NOT NULL REFERENCES ai_backends(id) ON DELETE CASCADE,
    model TEXT,
    PRIMARY KEY (member_id, task, position)
);
INSERT INTO ai_routes_new SELECT member_id, task, position, backend_id, model FROM ai_routes;
DROP TABLE ai_routes;
ALTER TABLE ai_routes_new RENAME TO ai_routes;
INSERT INTO ai_routes (member_id, task, position, backend_id, model)
SELECT member_id, 'recipes', position, backend_id, model FROM ai_routes
WHERE task = 'structured_misc';
