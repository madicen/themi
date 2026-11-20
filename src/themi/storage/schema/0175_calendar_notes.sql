-- WL7: an event's notes (its description), as plain text and shortened, for the wall's
-- Event view only. They never reach the model: what others write into an invitation is
-- the riskiest text there is, and the wall only shows it, escaped.
ALTER TABLE calendar_entries ADD COLUMN notes TEXT NOT NULL DEFAULT '';
