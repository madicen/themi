-- SL3: the thread a message is in (its parent's ts), so Themi answers where it was asked.
ALTER TABLE slack_messages ADD COLUMN thread_ts TEXT;
