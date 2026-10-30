-- P4: a 👎 on one of Themi's replies marks it as the wrong thing, for review. The outbox
-- knows which reply sent each message, so a reaction finds its reply. A marked reply (its
-- tools and model calls too) outlives the week's clean-up until it's labelled.
ALTER TABLE outbox ADD COLUMN reply_id INTEGER;
CREATE INDEX outbox_reply ON outbox (reply_id);

ALTER TABLE replies ADD COLUMN marked_at TEXT;
ALTER TABLE replies ADD COLUMN label TEXT
    CHECK (label IN ('router_miss', 'model_choice', 'no_tool_needed', 'not_wrong'));
ALTER TABLE replies ADD COLUMN right_tool TEXT;  -- what it should have used; 'none' for no tool
ALTER TABLE replies ADD COLUMN labelled_at TEXT;
