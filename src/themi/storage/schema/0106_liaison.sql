-- 34a: notes one family member asks Themi to pass on to another ("tell him the vet called").
-- `urgency`: urgent (now, even at night), today (by early evening at the latest) or whenever
-- (the recipient's next good window). `outbox_id`: the message that carries it;
-- `delivered_at`: when it went. `kind` leaves room for 34b's alignment prompts.
CREATE TABLE liaison_items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'relay' CHECK (kind IN ('relay')),
    from_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    to_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK (urgency IN ('urgent', 'today', 'whenever')),
    outbox_id INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX liaison_items_from ON liaison_items (from_member_id, delivered_at);
CREATE INDEX liaison_items_outbox ON liaison_items (outbox_id);
