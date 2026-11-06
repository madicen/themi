-- RC1a: the family cookbook, read from its Google Doc into Themi's own copy.
-- One cookbook for the household: the doc, the linked Google account that can open it
-- (drive.file: picked in Google's file picker), and what Themi last read.
CREATE TABLE cookbook (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    doc_id TEXT,
    account_id INTEGER REFERENCES linked_accounts(id) ON DELETE SET NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,  -- who chose it
    title TEXT,
    version TEXT,             -- Drive's version at the last read: unchanged means no re-read
    revision TEXT,            -- the Docs revision id at the last read (RC5 writes against it)
    read_at TEXT,
    problem TEXT,             -- why the last read failed, in plain words
    diet TEXT NOT NULL DEFAULT 'vegan',  -- RC4: web recipes searched and checked for this
    guides_offered INTEGER NOT NULL DEFAULT 0,  -- the References charts offered as guides
    updated_at TEXT
);
INSERT INTO cookbook (id) VALUES (1);

-- A recipe: from the doc (key = its heading id) or from the web (RC4a, key 'web:<n>').
-- Recipes gone from the doc are marked removed, not deleted, so a cooking session or a
-- grocery card that names one keeps working.
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL CHECK (source IN ('doc', 'web')),
    url TEXT,
    section TEXT NOT NULL DEFAULT '',
    subsection TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    ingredients TEXT NOT NULL DEFAULT '[]',  -- JSON [{"text", "group"}]
    steps TEXT NOT NULL DEFAULT '[]',        -- JSON [{"text", "group"}]
    notes TEXT NOT NULL DEFAULT '[]',        -- JSON [text]
    source_text TEXT NOT NULL DEFAULT '',    -- "Source: ..." as written
    kind TEXT NOT NULL DEFAULT 'recipe' CHECK (kind IN ('recipe', 'chart')),
    chart TEXT NOT NULL DEFAULT '[]',        -- JSON rows, the first the header
    yield_count INTEGER,                     -- as written in the recipe
    yield_said INTEGER,                      -- RC2b: what someone told Themi it makes
    needs_look TEXT NOT NULL DEFAULT '',     -- why the parser had to guess, "; "-joined
    words TEXT NOT NULL DEFAULT '',          -- ingredient lines and notes, for search
    hash TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,     -- order in the doc
    removed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX recipes_source ON recipes (source, removed_at);

CREATE VIRTUAL TABLE recipes_fts USING fts5(
    name, section, words, content='recipes', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER recipes_ai AFTER INSERT ON recipes BEGIN
    INSERT INTO recipes_fts (rowid, name, section, words)
    VALUES (new.id, new.name, new.section, new.words);
END;
CREATE TRIGGER recipes_ad AFTER DELETE ON recipes BEGIN
    INSERT INTO recipes_fts (recipes_fts, rowid, name, section, words)
    VALUES ('delete', old.id, old.name, old.section, old.words);
END;
CREATE TRIGGER recipes_au AFTER UPDATE ON recipes BEGIN
    INSERT INTO recipes_fts (recipes_fts, rowid, name, section, words)
    VALUES ('delete', old.id, old.name, old.section, old.words);
    INSERT INTO recipes_fts (rowid, name, section, words)
    VALUES (new.id, new.name, new.section, new.words);
END;
