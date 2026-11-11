-- MM2: the morning tray. A proactive message held for the morning message's buttons keeps
-- status 'queued' and names its tray ('tasks', 'email', 'other') until a tap sends it.
ALTER TABLE outbox ADD COLUMN tray TEXT;
CREATE INDEX outbox_tray ON outbox (member_id, tray);
-- MM1-MM4: the morning message that went (its outbox row), the buttons tapped on it, and
-- when the noon recap went.
ALTER TABLE morning_summaries ADD COLUMN outbox_id INTEGER;
ALTER TABLE morning_summaries ADD COLUMN tapped TEXT NOT NULL DEFAULT '';
ALTER TABLE morning_summaries ADD COLUMN recap_at TEXT;
