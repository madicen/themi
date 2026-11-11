-- F41b, bug #198: a session started from the website's Cook button never posts to chat.
ALTER TABLE cooking_sessions ADD COLUMN from_page INTEGER NOT NULL DEFAULT 0;
