-- F29a (idea #150): when Themi moves an event's start earlier and keeps its end, the
-- description says when it really starts ("Starts at 4:00 pm. The time before it is
-- set-up time."). On by default; each person can turn it off on Settings.
ALTER TABLE members ADD COLUMN setup_note INTEGER NOT NULL DEFAULT 1;
