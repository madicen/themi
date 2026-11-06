-- F31a (bug #169): when a routine tick was last seen on the wall, or reached it from Themi.
-- A tick the wall had and doesn't any more was unticked there, so Themi unticks it too;
-- one that never reached the wall is sent again.
ALTER TABLE routine_ticks ADD COLUMN on_wall_at TEXT;
