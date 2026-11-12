-- EX2a: when Themi last read the conversation around an entry for its empty fields, so it
-- reads it once.
ALTER TABLE expense_entries ADD COLUMN context_checked_at TEXT;
