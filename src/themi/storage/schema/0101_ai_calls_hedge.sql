-- P2b: an interactive chat call still out after a few seconds is sent again. NULL when it
-- wasn't; 'first' or 'second', whichever answered (or 'first' when both failed).
ALTER TABLE ai_calls ADD COLUMN hedge TEXT;
