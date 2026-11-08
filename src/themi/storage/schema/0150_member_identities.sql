-- CR20a2: how each member is reached on each channel ("telegram": their Telegram user id),
-- in place of members.telegram_user_id. One identity per member per channel, and one
-- member per identity.
CREATE TABLE member_identities (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (member_id, channel),
    UNIQUE (channel, external_id)
);
INSERT INTO member_identities (member_id, channel, external_id, created_at)
    SELECT id, 'telegram', CAST(telegram_user_id AS TEXT), updated_at
    FROM members WHERE telegram_user_id IS NOT NULL;
-- SQLite can't drop a UNIQUE column without rebuilding members, which every table points
-- at (with cascades), so the old column is emptied and nothing reads it any more.
UPDATE members SET telegram_user_id = NULL;
