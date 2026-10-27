-- K2: a morning summary of the day, if a person wants one: at a time of their choosing
-- (NULL: off), and on empty days too only if they say so.
ALTER TABLE members ADD COLUMN morning_summary TEXT;  -- 'HH:MM'
ALTER TABLE members ADD COLUMN morning_summary_empty INTEGER NOT NULL DEFAULT 0;
CREATE TABLE morning_summaries (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (member_id, day)
);
