-- F55f (idea #239): calendars the family turned off in the wall's week ahead, by their
-- calendar id. Only the week ahead leaves them out; nothing else on the wall or in Themi.
CREATE TABLE wall_hidden_calendars (
    calendar_id TEXT PRIMARY KEY,
    hidden_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    hidden_at TEXT NOT NULL
);
