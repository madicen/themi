-- F57a: other words someone might use when a fact matters ("Dad, hospital, visit" for
-- Stanford's visiting hours), searched with the fact. The full-text index gains them as
-- a third column, so it's rebuilt with its triggers.
ALTER TABLE facts ADD COLUMN keywords TEXT NOT NULL DEFAULT '';

DROP TRIGGER facts_ai;
DROP TRIGGER facts_ad;
DROP TRIGGER facts_au;
DROP TABLE facts_fts;

CREATE VIRTUAL TABLE facts_fts USING fts5(
    subject, fact, keywords, content='facts', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts (rowid, subject, fact, keywords)
    VALUES (new.id, new.subject, new.fact, new.keywords);
END;
CREATE TRIGGER facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, subject, fact, keywords)
    VALUES ('delete', old.id, old.subject, old.fact, old.keywords);
END;
CREATE TRIGGER facts_au AFTER UPDATE OF subject, fact, keywords ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, subject, fact, keywords)
    VALUES ('delete', old.id, old.subject, old.fact, old.keywords);
    INSERT INTO facts_fts (rowid, subject, fact, keywords)
    VALUES (new.id, new.subject, new.fact, new.keywords);
END;
INSERT INTO facts_fts (facts_fts) VALUES ('rebuild');
