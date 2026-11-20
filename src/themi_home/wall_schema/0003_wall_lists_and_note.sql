-- WL5b: the wall changes more than ticks now (a to-do moved to tomorrow, given to the other
-- person, made a family one, reworded, added), so its category says so.
UPDATE action_categories SET label = 'Change to-dos and lists from the wall'
    WHERE name = 'wall_tap';

-- Themi's note put off from the wall: "Later tonight", "In the morning". Keyed by what the
-- note is about ("task-12", "alert-Wind Advisory"), until a moment (UTC).
CREATE TABLE wall_note_quiet (
    note_key TEXT PRIMARY KEY,
    until TEXT NOT NULL
);
