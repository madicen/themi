-- WA1: what a heads-up worked out, kept so the wall's countdown reads it rather than looking
-- the drive up again: when to leave, when getting ready starts, the drive and whether it had
-- live traffic, and the event's title as the heads-up said it.
ALTER TABLE travel_headsups ADD COLUMN leave_by TEXT;
ALTER TABLE travel_headsups ADD COLUMN ready_from TEXT;
ALTER TABLE travel_headsups ADD COLUMN drive_minutes INTEGER;
ALTER TABLE travel_headsups ADD COLUMN traffic INTEGER NOT NULL DEFAULT 0;
ALTER TABLE travel_headsups ADD COLUMN title TEXT NOT NULL DEFAULT '';
