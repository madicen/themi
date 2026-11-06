-- F30d (idea #162): web lookups, counted for a daily cap per family. What was searched
-- isn't kept: only that a search or page read happened, by whom and when.
CREATE TABLE web_lookups (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('search', 'read')),
    created_at TEXT NOT NULL
);
CREATE INDEX web_lookups_created ON web_lookups (created_at);
