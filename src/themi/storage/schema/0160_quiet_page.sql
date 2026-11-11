-- CK13, bug #192: chat stays quiet while a session page is open. When the body double page
-- last asked for its state, and a block-end question shown there but not yet sent to chat.
ALTER TABLE body_double_sessions ADD COLUMN page_at TEXT;
ALTER TABLE body_double_sessions ADD COLUMN ask_held INTEGER NOT NULL DEFAULT 0;
