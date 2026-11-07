-- BD5a: each person's built-in loop and volume for the session page (nothing plays until
-- they tap it the first time).
ALTER TABLE members ADD COLUMN body_double_sound TEXT NOT NULL DEFAULT 'lofi';
ALTER TABLE members ADD COLUMN body_double_volume INTEGER NOT NULL DEFAULT 50;
