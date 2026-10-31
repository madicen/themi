-- O1b (Erin's idea #94): when the rest of a day is spread out, at most this many things on
-- any one day; 0 goes by what the person usually gets done in a day.
ALTER TABLE members ADD COLUMN day_budget INTEGER NOT NULL DEFAULT 0;
