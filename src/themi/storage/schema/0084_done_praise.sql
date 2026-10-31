-- F19b (Erin's idea #102): a short warm word when a task is done in Themi; off per person.
ALTER TABLE members ADD COLUMN done_praise INTEGER NOT NULL DEFAULT 1;
