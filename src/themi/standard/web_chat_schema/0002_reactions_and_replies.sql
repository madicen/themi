-- WC1: reactions and replies in the website's chat. `reactions` on Themi's message is the
-- member's reaction; on theirs it is Themi's (👀, ✍). `reply_to` is the message this one
-- answers, one of the same member's.
ALTER TABLE web_chat_messages ADD COLUMN reactions TEXT NOT NULL DEFAULT '[]';
ALTER TABLE web_chat_messages ADD COLUMN reply_to INTEGER REFERENCES web_chat_messages(id)
    ON DELETE SET NULL;
