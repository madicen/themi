-- P3: how well P1's tool groups are chosen. Per reply: the groups sent at the start
-- (comma-separated, '' for the core only), the groups more_tools added during it, and how
-- many tools went with the first model call. NULL on replies from before P3.
ALTER TABLE replies ADD COLUMN groups TEXT;
ALTER TABLE replies ADD COLUMN groups_added TEXT;
ALTER TABLE replies ADD COLUMN tools_sent INTEGER;
