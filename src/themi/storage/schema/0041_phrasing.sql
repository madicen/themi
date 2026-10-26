-- Idea #12: plain language by default; each person can choose gentle phrasing and add
-- their own notes on how they like things said.
ALTER TABLE members ADD COLUMN phrasing TEXT NOT NULL DEFAULT 'plain'
    CHECK (phrasing IN ('plain', 'gentle'));
ALTER TABLE members ADD COLUMN phrasing_notes TEXT NOT NULL DEFAULT '';
