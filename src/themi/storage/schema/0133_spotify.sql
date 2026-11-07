-- BD5b: each person's own Spotify link (PKCE sign-in; the refresh token encrypted), the
-- link's one-time state, the "music" trust tier (automatic to start: done, then told), and
-- what a body double session played (for BD5c).
CREATE TABLE spotify_links (
    member_id INTEGER PRIMARY KEY REFERENCES members (id) ON DELETE CASCADE,
    refresh_token BLOB NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    premium INTEGER NOT NULL DEFAULT 0,
    linked_at TEXT NOT NULL
);
CREATE TABLE spotify_states (
    state_hash TEXT PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    verifier BLOB NOT NULL,
    expires_at TEXT NOT NULL
);
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('music', 'Play music on your own Spotify', 'family', 2, 2, '1970-01-01T00:00:00+00:00');
-- "builtin:rain" or "spotify:playlist:..." and its name, what played during the session
ALTER TABLE body_double_sessions ADD COLUMN music TEXT;
ALTER TABLE body_double_sessions ADD COLUMN music_name TEXT;
