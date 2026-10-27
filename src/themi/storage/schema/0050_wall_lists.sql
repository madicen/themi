-- L1b: Themi's lists kept in step with the wall's. Each linked item remembers how the wall
-- had it at the last sync, so a change on either side can be told apart; `pending` marks a
-- change made in Themi since, which wins over one made on the wall.
ALTER TABLE list_items ADD COLUMN wall_title TEXT;
ALTER TABLE list_items ADD COLUMN wall_done INTEGER;
ALTER TABLE list_items ADD COLUMN pending INTEGER NOT NULL DEFAULT 0;
-- Removed in Themi, still to go from the wall.
CREATE TABLE list_wall_removals (
    kind TEXT NOT NULL CHECK (kind IN ('todo', 'list')),
    wall_id TEXT NOT NULL,
    PRIMARY KEY (kind, wall_id)
);
-- The category now covers putting a whole list on the wall (add_to_wall_list folded into
-- the list tools).
UPDATE action_categories SET label = 'Put one of Themi''s lists on the Cozyla wall'
WHERE name = 'wall_list_add';
