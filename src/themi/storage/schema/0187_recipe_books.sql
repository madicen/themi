-- RC8a: the recipe docs are a list of recipe books, not two fixed tables. The family
-- cookbook (id 1, role 'main') and Recipes to try (id 2, role 'trying') are its first rows;
-- RC8b adds books of their own ('shelf'), such as the vegan cheese recipes. Each book says
-- how much it shows up: in meal ideas, in a search that doesn't name it, with a save button
-- on web recipes.
CREATE TABLE recipe_books (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,         -- 'cookbook', 'to_try', or 'b<id>' for one added later
    name TEXT NOT NULL,               -- how Themi says it: "the cookbook", "Recipes to try"
    role TEXT NOT NULL CHECK (role IN ('main', 'trying', 'shelf')),
    doc_id TEXT,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,  -- who chose it
    title TEXT,
    version TEXT,             -- Drive's version at the last read: unchanged means no re-read
    revision TEXT,            -- the Docs revision id at the last read (writes go against it)
    read_at TEXT,
    problem TEXT,             -- why the last read failed, in plain words
    diet TEXT NOT NULL DEFAULT 'vegan',  -- RC4: the main book's, for web recipes
    guides_offered INTEGER NOT NULL DEFAULT 0,  -- its reference charts offered as guides
    position INTEGER NOT NULL DEFAULT 0,
    in_meal_ideas INTEGER NOT NULL DEFAULT 1,   -- offered by "what can we make?"
    found_unasked INTEGER NOT NULL DEFAULT 1,   -- found by a search that doesn't name it
    save_button INTEGER NOT NULL DEFAULT 1,     -- a save button on web recipes' cards
    sub_recipe_sections TEXT NOT NULL DEFAULT '[]',  -- JSON: base recipes others use
    reference_sections TEXT NOT NULL DEFAULT '[]',   -- JSON: charts and guides, not recipes
    removed_at TEXT,          -- RC8b: no longer read (its recipes are marked removed)
    updated_at TEXT
);

INSERT INTO recipe_books (id, key, name, role, doc_id, account_id, member_id, title, version,
                          revision, read_at, problem, diet, guides_offered, position,
                          sub_recipe_sections, reference_sections, updated_at)
SELECT 1, 'cookbook', 'the cookbook', 'main', doc_id, account_id, member_id, title, version,
       revision, read_at, problem, diet, guides_offered, 0, '["Ingredients"]', '["References"]',
       updated_at
FROM cookbook;

INSERT INTO recipe_books (id, key, name, role, doc_id, account_id, member_id, title, version,
                          revision, read_at, problem, position, updated_at)
SELECT 2, 'to_try', 'Recipes to try', 'trying', doc_id, account_id, member_id, title, version,
       revision, read_at, problem, 1, updated_at
FROM try_doc;

-- Which book a recipe is from. NULL is the main book: web recipes (in no doc yet) and rows
-- written without one. `recipes.book` (0172) stays but is no longer read: dropping it means
-- rebuilding `recipes`, and this migration runs in one transaction with foreign keys on, so
-- dropping the table would cascade-delete cooking sessions, step titles, mixes and weights.
ALTER TABLE recipes ADD COLUMN book_id INTEGER REFERENCES recipe_books(id);
UPDATE recipes SET book_id = CASE book WHEN 'to_try' THEN 2 ELSE 1 END WHERE source = 'doc';
CREATE INDEX recipes_book ON recipes (book_id, removed_at);

DROP TABLE cookbook;
DROP TABLE try_doc;
