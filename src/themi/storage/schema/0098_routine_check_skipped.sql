-- F23b: a check they tapped "Skip today" on stays skipped when an item is ticked elsewhere.
ALTER TABLE routine_day_checks ADD COLUMN skipped_at TEXT;
