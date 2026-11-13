-- F36b (Erin's idea #185): a Things to Buy item can be "someday" (research included), kept
-- for the person who added it (`added_by`). `someday_asked_at`: when its adder was last
-- nudged about it, or answered, so the weekly nudge picks the one asked about least lately.
ALTER TABLE list_items ADD COLUMN someday INTEGER NOT NULL DEFAULT 0;
ALTER TABLE list_items ADD COLUMN someday_asked_at TEXT;
