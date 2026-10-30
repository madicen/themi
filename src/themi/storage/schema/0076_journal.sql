-- M1: a private journal per person, one entry a day, written once the day is over from
-- that day's messages: the topics talked about and what was decided. A deleted entry keeps
-- its row (and nothing else) so it isn't written again.
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    topics TEXT NOT NULL DEFAULT '[]',            -- JSON list of short phrases
    decided TEXT NOT NULL DEFAULT '[]',           -- JSON list of one-line decisions
    text TEXT NOT NULL DEFAULT '',                -- both, for search
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (member_id, day)
);

CREATE VIRTUAL TABLE journal_fts USING fts5(
    text, content='journal_entries', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER journal_ai AFTER INSERT ON journal_entries BEGIN
    INSERT INTO journal_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER journal_ad AFTER DELETE ON journal_entries BEGIN
    INSERT INTO journal_fts (journal_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER journal_au AFTER UPDATE ON journal_entries BEGIN
    INSERT INTO journal_fts (journal_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO journal_fts (rowid, text) VALUES (new.id, new.text);
END;
