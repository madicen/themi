-- F9a: "if I miss a day, prompt me the next day". A third choice for a missed round,
-- kept in its own column because `missed` has a CHECK constraint (0030) that SQLite can't
-- change without rebuilding `tasks`. With it set, `missed` stays 'roll': a round that
-- can't move to the next day (the next round comes first) rolls on.
ALTER TABLE tasks ADD COLUMN missed_next_day INTEGER NOT NULL DEFAULT 0;
