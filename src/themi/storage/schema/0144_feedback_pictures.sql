-- F34o: a screenshot sent with a bug report or idea, kept with it, encrypted with the key
-- kept outside the database. Deleted when the report is marked reviewed, after 60 days, or
-- with its member.
CREATE TABLE feedback_pictures (
    id INTEGER PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    mime_type TEXT NOT NULL,
    data BLOB NOT NULL,                            -- encrypted
    created_at TEXT NOT NULL
);
CREATE INDEX feedback_pictures_by_report ON feedback_pictures (feedback_id);
