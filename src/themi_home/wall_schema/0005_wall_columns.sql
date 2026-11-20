-- F53: the wall's columns as the family chose them: each person ("m3") and Together
-- ("together") in the order they stand, and the colour each one is drawn in (a tone class,
-- "p0" ... "p6" or "family"). No rows means the defaults: the people in the household's
-- order with Together in the middle, each person by their place (p0 to p3).
CREATE TABLE wall_columns (
    key TEXT PRIMARY KEY,
    position INTEGER NOT NULL,
    tone TEXT NOT NULL,
    updated_by INTEGER REFERENCES members(id),
    updated_at TEXT NOT NULL
);
