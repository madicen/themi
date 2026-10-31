-- O1a: how many things "for now" when it's too much; the person's own number.
ALTER TABLE members ADD COLUMN focus_count INTEGER NOT NULL DEFAULT 3;
