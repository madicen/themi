-- F29g (bug #152, idea #153): list items with sub-items, at any depth. Existing items are
-- at the top level. A sub-item goes with its parent.
ALTER TABLE list_items ADD COLUMN parent_id INTEGER REFERENCES list_items(id) ON DELETE CASCADE;
CREATE INDEX list_items_parent ON list_items (parent_id);
-- How each person sees a list's levels: "dashes" (- , -- ), "bullets" or "numbers" (1.1.).
ALTER TABLE members ADD COLUMN list_style TEXT NOT NULL DEFAULT 'dashes'
    CHECK (list_style IN ('dashes', 'bullets', 'numbers'));
