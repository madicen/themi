-- L2a (Erin's idea #6): a "things to buy" list for what isn't food, and where things come
-- from. `purpose` marks the household's one list for it.
ALTER TABLE lists ADD COLUMN purpose TEXT;
CREATE UNIQUE INDEX lists_purpose ON lists (purpose) WHERE purpose IS NOT NULL;
-- The wall list's name as of the last sync, so a rename on either side can be told apart.
ALTER TABLE lists ADD COLUMN wall_name TEXT;
UPDATE lists SET wall_name = name WHERE cozyla_list_id IS NOT NULL;

-- What's known about an item, by name: food (groceries) or not (things to buy), and the
-- store it usually comes from. Learned from what people say and from receipts.
CREATE TABLE item_homes (
    name_key TEXT PRIMARY KEY,
    kind TEXT CHECK (kind IN ('food', 'other')),
    store TEXT,
    updated_at TEXT NOT NULL
);
