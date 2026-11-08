-- CR21b: the routine ticks the wall has (seen there, or sent and taken), in place of
-- routine_ticks.on_wall_at, which is left as it was and no longer read. A tick taken back
-- takes its row with it.
CREATE TABLE wall_seen_ticks (
    item_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (item_id, day),
    FOREIGN KEY (item_id, day) REFERENCES routine_ticks (item_id, day) ON DELETE CASCADE
);
INSERT INTO wall_seen_ticks (item_id, day, seen_at)
    SELECT item_id, day, on_wall_at FROM routine_ticks WHERE on_wall_at IS NOT NULL;
