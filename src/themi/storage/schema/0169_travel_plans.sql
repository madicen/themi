-- F46c (bug #218): where they said they'll leave from for an event, kept with it so a
-- later question and the heads-up use it too. One row per person, event and day (a moved
-- event the same day keeps it); `origin` is their words ("in-laws", an address), '' home.
-- F46d (bug #219): `arrive_early`, minutes before the start they want to be there.
CREATE TABLE travel_plans (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    event_key TEXT NOT NULL,
    day TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    arrive_early INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (member_id, event_key, day)
);
