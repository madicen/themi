-- GK2: each linked person's Keep list shows Themi's grocery list, both ways. Each Keep item
-- Themi knows: 'shown' (stands for a grocery_list row while it's needed), 'done' (checked
-- off for a bought item), or 'skipped' (no name Themi can keep). `confirmed`: a read of Keep
-- has shown the state Themi last wrote; until then a difference is a write Keep dropped.
-- GK1's rows only said "taken"; the items they name are checked off in Keep and stay so.
DROP TABLE keep_items;
CREATE TABLE keep_items (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    text TEXT NOT NULL,
    grocery_id INTEGER REFERENCES grocery_list(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('shown', 'done', 'skipped')),
    confirmed INTEGER NOT NULL DEFAULT 0,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (member_id, item_id)
);
