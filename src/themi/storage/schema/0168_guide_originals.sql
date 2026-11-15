-- F29hb (idea #148): a guide read from a photo or a PDF keeps what was sent beside its
-- text, encrypted with the key kept outside the database. Replaced when the guide is read
-- again, and deleted with the guide (and so with its owner).
CREATE TABLE guide_originals (
    id INTEGER PRIMARY KEY,
    guide_id INTEGER NOT NULL REFERENCES guides(id) ON DELETE CASCADE,
    mime_type TEXT NOT NULL,
    data BLOB NOT NULL,                            -- encrypted
    created_at TEXT NOT NULL
);
CREATE INDEX guide_originals_by_guide ON guide_originals (guide_id);
