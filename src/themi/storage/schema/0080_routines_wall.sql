-- R1b: Themi's routine items on the Cozyla wall, both ways. A link per item: its routine on
-- the wall once made, and whether Themi has a change still to send. Triggers mark changes,
-- so every way an item changes is caught. `version` grows with every change, so one made
-- while the sync is sending isn't marked sent by mistake.
CREATE TABLE routine_item_links (
    item_id INTEGER PRIMARY KEY REFERENCES routine_items(id) ON DELETE CASCADE,
    wall_id INTEGER UNIQUE,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'done')),
    version INTEGER NOT NULL DEFAULT 0
);
INSERT INTO routine_item_links (item_id) SELECT id FROM routine_items;

-- Routines on the wall Themi has to delete (their items were removed in Themi).
CREATE TABLE routine_wall_deletes (wall_id INTEGER PRIMARY KEY);

-- The wall's routines as they were at the last sync, to tell what changed there since.
CREATE TABLE routine_wall_seen (
    wall_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    part TEXT NOT NULL,
    days TEXT NOT NULL
);

CREATE TRIGGER routine_item_made AFTER INSERT ON routine_items BEGIN
    INSERT OR IGNORE INTO routine_item_links (item_id) VALUES (new.id);
END;
CREATE TRIGGER routine_item_changed
AFTER UPDATE OF title, days, only_on, routine_id, position ON routine_items BEGIN
    UPDATE routine_item_links SET state = 'pending', version = version + 1
    WHERE item_id = new.id;
END;
CREATE TRIGGER routine_item_removed BEFORE DELETE ON routine_items BEGIN
    INSERT OR IGNORE INTO routine_wall_deletes (wall_id)
    SELECT wall_id FROM routine_item_links WHERE item_id = old.id AND wall_id IS NOT NULL;
END;
CREATE TRIGGER routine_moved AFTER UPDATE OF starts ON routines BEGIN
    UPDATE routine_item_links SET state = 'pending', version = version + 1
    WHERE item_id IN (SELECT id FROM routine_items WHERE routine_id = new.id);
END;
