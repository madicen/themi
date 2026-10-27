-- L1a (Erin's idea #7): named lists kept by Themi, "packing for the trip", "gift ideas".
-- A list is the household's (owner_id NULL) or one person's, seen only by them. Ticked
-- items stay, crossed off, until someone clears them.
CREATE TABLE lists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id INTEGER REFERENCES members(id) ON DELETE CASCADE,  -- NULL: the household's
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    cozyla_list_id TEXT  -- L1b: the wall list it's kept in step with, if any
);
CREATE TABLE list_items (
    id INTEGER PRIMARY KEY,
    list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    done_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    done_at TEXT,
    added_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    added_at TEXT NOT NULL,
    cozyla_todo_id TEXT  -- L1b
);
CREATE INDEX list_items_list ON list_items (list_id, id);

-- Items the model inferred wait for a yes; a list goes only when they named it.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('list_add', 'Add items to one of Themi''s lists', 'family', 2, '1970-01-01T00:00:00+00:00'),
    ('list_delete', 'Delete one of Themi''s lists', 'family', 2, '1970-01-01T00:00:00+00:00');
