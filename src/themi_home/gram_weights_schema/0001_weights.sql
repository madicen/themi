-- GW1: where each weight in the family's weights guide came from. The guide's text is where
-- the weight is kept; a key with no row here is the family's own line.
CREATE TABLE gram_weights_meta (
    key TEXT PRIMARY KEY,           -- the ingredient's key (sorted, stemmed words)
    name TEXT NOT NULL,             -- the ingredient as said ("almond flour")
    source TEXT NOT NULL,           -- family, web, weighed, corrected, recipe, wanted
    urls TEXT NOT NULL DEFAULT '[]',
    found_at TEXT NOT NULL,
    agrees INTEGER NOT NULL DEFAULT 0,  -- how many web sources agreed (GW3)
    previous TEXT,                  -- the guide line before the last correction (GW5)
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL
);
-- Two names for one ingredient ("plain flour" is "flour"), beside the seeded ones.
CREATE TABLE gram_aliases (
    alias TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
-- Adding or changing a line in the family's weights guide: done, then said (the plan's
-- "do, then tell"). A family can still turn it to asking first on the Trust page.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('gram_weight_save', 'Add or change a weight in your weights guide', 'family', 2, 2,
     '1970-01-01T00:00:00+00:00');

-- GW2: recipes already read for weights they state, by the digest of their ingredient lines,
-- so a recipe is read again only when its words change.
CREATE TABLE gram_weights_seen (
    recipe_id INTEGER PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

-- GW3: ingredients to look up online, one row per key. A row from a recipe on the website
-- or the cook screen has no recipe; at most 5 lookups a recipe each time the job runs.
CREATE TABLE gram_weights_queue (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    asked_at TEXT NOT NULL
);
