-- F15b (bug #57, Michael's held cards): a message or a card that's no use late. An outbox
-- row past expires_at is dropped, never sent; a pending action past it lapses.
ALTER TABLE outbox ADD COLUMN expires_at TEXT;
ALTER TABLE pending_actions ADD COLUMN expires_at TEXT;
