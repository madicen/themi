-- F29ha (idea #148): the family's own guides (a cooking chart, care instructions), given
-- as text in chat or on the website. The household's, or just their owner's.
CREATE TABLE guides (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    owner_id INTEGER REFERENCES members(id) ON DELETE CASCADE,  -- NULL: the household's
    created_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX guides_owner ON guides (owner_id);
