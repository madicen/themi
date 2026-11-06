-- F29c (idea #156): a note held for later gets a "Send now" button on its confirmation.
-- The confirmation's outbox row, so the button goes once the note has gone.
ALTER TABLE liaison_items ADD COLUMN card_outbox_id INTEGER;
