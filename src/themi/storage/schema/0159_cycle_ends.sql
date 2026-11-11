-- F40b, idea #196: when a running appliance's cycle should end, from the minutes left at its
-- latest read (LG's timer, Home Connect's remaining time), so Home can say "done around".
ALTER TABLE appliance_cycles ADD COLUMN ends_at TEXT;
