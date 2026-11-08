-- CR21d: 0001 copied the ticks the wall had into wall_seen_ticks; the old column goes.
ALTER TABLE routine_ticks DROP COLUMN on_wall_at;
