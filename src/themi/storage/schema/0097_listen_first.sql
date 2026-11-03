-- F22e (Erin's idea #125): listen first, and ask before problem-solving. On by default.
ALTER TABLE members ADD COLUMN listen_first INTEGER NOT NULL DEFAULT 1;
