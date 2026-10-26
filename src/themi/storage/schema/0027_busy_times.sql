-- Busy times (F3): weekly windows when Themi holds its own messages, like quiet
-- hours. JSON list of {"days": [0-6, Monday first], "start": "HH:MM", "end": "HH:MM"}.
ALTER TABLE members ADD COLUMN busy_times TEXT NOT NULL DEFAULT '[]';
