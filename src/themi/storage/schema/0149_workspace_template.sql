-- CR9: the family is a workspace, made from a template (themi.toml's, or the family's).
-- The table keeps its name: every query that reads it stays as it is.
ALTER TABLE family ADD COLUMN template TEXT NOT NULL DEFAULT 'family';
