-- WX3: whether the home is in the US, so NWS's warnings are asked for (WEATHER_ALERTS=auto).
-- Asked once per place: a moved home is asked about again.
CREATE TABLE weather_home (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    in_us INTEGER NOT NULL
);
