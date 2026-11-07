-- F34i (idea #183): their own Spotify playlists, read once when a session starts, for its
-- music offer, "More" and the session page: JSON [{"uri", "name", "link"}], newest first.
ALTER TABLE body_double_sessions ADD COLUMN playlists TEXT;
