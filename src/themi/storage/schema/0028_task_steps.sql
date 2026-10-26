-- Steps on tasks (F6a): a chore's steps, in the person's own words, as a JSON list
-- of strings. Tags such as "(Optional/Bonus)" are part of the text.
ALTER TABLE tasks ADD COLUMN steps TEXT NOT NULL DEFAULT '[]';
