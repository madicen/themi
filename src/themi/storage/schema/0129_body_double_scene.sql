-- BD3b: the session page's chameleon cheers for a moment after a finished block or step,
-- and stays attentive while they chat on the page during a break.
ALTER TABLE body_double_sessions ADD COLUMN cheer_until TEXT;
ALTER TABLE body_double_sessions ADD COLUMN chat_at TEXT;  -- their last message from the page
