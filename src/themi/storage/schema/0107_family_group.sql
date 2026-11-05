-- 34b: the family group and alignment prompts.

-- The one Telegram group Themi treats as the family's: an admin links it with /familygroup
-- in the group. `chat_id` changes when Telegram turns the group into a supergroup.
CREATE TABLE family_group (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    chat_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);

-- `chat_id`: NULL for the member's own chat, else the group it goes to (a reply to
-- something said in the group, or a question for the family). `shared_buttons`: its buttons
-- are for anyone in the family to tap, not only `member_id`.
ALTER TABLE outbox ADD COLUMN chat_id INTEGER;
ALTER TABLE outbox ADD COLUMN shared_buttons INTEGER NOT NULL DEFAULT 0;

-- A button any family member may tap (an alignment question in the group); each tap is
-- the handler's to record, so the keyboard isn't used up by the first one.
ALTER TABLE callback_tokens ADD COLUMN anyone INTEGER NOT NULL DEFAULT 0;

-- `liaison_items.kind` gains 'alignment': a two-option question for both partners in the
-- group. It has no single recipient (`to_member_id` NULL); `topic` names what it settles,
-- `options` holds the two choices (JSON), `resolved_at` and `outcome` ('agreed' or
-- 'different') come once everyone has answered, and `rule_id` is the rule proposed from an
-- agreement. Nothing points at the table, so it's rebuilt as it is.
CREATE TABLE liaison_items_new (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'relay' CHECK (kind IN ('relay', 'alignment')),
    from_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    to_member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK (urgency IN ('urgent', 'today', 'whenever')),
    outbox_id INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    topic TEXT,
    options TEXT,
    resolved_at TEXT,
    outcome TEXT CHECK (outcome IN ('agreed', 'different')),
    rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL
);
INSERT INTO liaison_items_new (id, kind, from_member_id, to_member_id, body, urgency,
    outbox_id, created_at, delivered_at)
SELECT id, kind, from_member_id, to_member_id, body, urgency, outbox_id, created_at,
    delivered_at FROM liaison_items;
DROP TABLE liaison_items;
ALTER TABLE liaison_items_new RENAME TO liaison_items;
CREATE INDEX liaison_items_from ON liaison_items (from_member_id, delivered_at);
CREATE INDEX liaison_items_outbox ON liaison_items (outbox_id);

-- Each person's tap on an alignment question (their latest, until it's settled).
CREATE TABLE alignment_answers (
    item_id INTEGER NOT NULL REFERENCES liaison_items(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    choice INTEGER NOT NULL CHECK (choice IN (0, 1)),
    answered_at TEXT NOT NULL,
    PRIMARY KEY (item_id, member_id)
);
