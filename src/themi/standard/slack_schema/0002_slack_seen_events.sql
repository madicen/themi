-- SL2: Slack sends an event again when it thinks Themi missed it; each event's id is kept
-- for a day so a repeat is dropped.
CREATE TABLE slack_seen_events (
    event_id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
CREATE INDEX slack_seen_events_at ON slack_seen_events (seen_at);
