-- F34j (idea #182): when someone's day rolls over, as an hour after midnight (0 to 4). A
-- chore ticked at 12:40 am with their day ending at 3 counts for the day before.
ALTER TABLE members ADD COLUMN day_ends INTEGER NOT NULL DEFAULT 0;
