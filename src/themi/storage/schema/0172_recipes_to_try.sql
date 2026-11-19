-- F49h (idea #224): "Recipes to try", a second Google Doc read the same way as the cookbook:
-- recipes they want to try, not (yet) good enough for the cookbook.
CREATE TABLE try_doc (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    doc_id TEXT,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,  -- who chose it
    title TEXT,
    version TEXT,             -- Drive's version at the last read
    revision TEXT,            -- the Docs revision id at the last read
    read_at TEXT,
    problem TEXT,             -- why the last read failed, in plain words
    updated_at TEXT
);
INSERT INTO try_doc (id) VALUES (1);

-- Which doc a doc recipe came from; web recipes stay 'cookbook' (they aren't in either yet).
ALTER TABLE recipes ADD COLUMN book TEXT NOT NULL DEFAULT 'cookbook'
    CHECK (book IN ('cookbook', 'to_try'));
