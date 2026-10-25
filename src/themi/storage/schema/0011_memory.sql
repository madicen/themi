-- Things Themi has been told. Household facts are shared; personal ones are
-- seen only in that member's conversations. Pinned facts are in every prompt;
-- the rest are retrieved when a message mentions them.
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('family', 'member')),
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,  -- set for personal facts
    subject TEXT NOT NULL,
    fact TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'chat',          -- chat, repair, migrated, website
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_shown_at TEXT,                           -- last time it was put in front of the model
    CHECK ((scope = 'member') = (member_id IS NOT NULL))
);

CREATE VIRTUAL TABLE facts_fts USING fts5(
    subject, fact, content='facts', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts (rowid, subject, fact) VALUES (new.id, new.subject, new.fact);
END;
CREATE TRIGGER facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, subject, fact)
    VALUES ('delete', old.id, old.subject, old.fact);
END;
CREATE TRIGGER facts_au AFTER UPDATE OF subject, fact ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, subject, fact)
    VALUES ('delete', old.id, old.subject, old.fact);
    INSERT INTO facts_fts (rowid, subject, fact) VALUES (new.id, new.subject, new.fact);
END;

-- Facts remembered before this migration were household facts.
INSERT INTO facts (scope, subject, fact, source, created_by, created_at, updated_at)
SELECT 'family', subject, fact, 'migrated', member_id, created_at, created_at FROM scratch_facts;
DROP TABLE scratch_facts;

-- Each "you keep forgetting X": what was wrong and what was changed.
CREATE TABLE context_repairs (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    complaint TEXT NOT NULL,
    diagnosis TEXT NOT NULL CHECK (diagnosis IN
        ('never_stored', 'not_retrieved', 'stored_wrong', 'ignored')),
    fix TEXT NOT NULL,
    fact_id INTEGER REFERENCES facts(id) ON DELETE SET NULL,
    rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
