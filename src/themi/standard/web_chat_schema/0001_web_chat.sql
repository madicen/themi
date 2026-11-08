-- CR20b: the website's chat with Themi, for someone who uses only the site. What Themi
-- sends keeps its buttons (labels, kinds and payloads stay on the server, as Telegram's do).
CREATE TABLE web_chat_messages (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text TEXT NOT NULL,
    buttons TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    edited_at TEXT
);
CREATE INDEX web_chat_messages_member ON web_chat_messages (member_id, id);
