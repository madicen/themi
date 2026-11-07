-- F34g: how many pictures sent in chat Themi looks at for a member each day.
ALTER TABLE members ADD COLUMN picture_daily_cap INTEGER NOT NULL DEFAULT 30;
