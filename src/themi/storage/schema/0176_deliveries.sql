-- WL8: parcels on their way, from shipping emails, for the wall's note ("A delivery from
-- Chewy is due today"). Only the shop's name, the day and how far along it is: never what
-- is in it, since the wall is a shared screen and a parcel can be a present. `day` is the
-- household's local date it's expected (or came); kept two weeks.
CREATE TABLE deliveries (
    id INTEGER PRIMARY KEY,
    email_id INTEGER NOT NULL UNIQUE REFERENCES emails(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    shop TEXT NOT NULL,
    day TEXT NOT NULL,
    status TEXT NOT NULL,
    found_at TEXT NOT NULL
);
CREATE INDEX deliveries_day ON deliveries (day);
