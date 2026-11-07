-- F34hb: one body double session through several things in a row. Each part is its own
-- row (so each keeps its own outcome for BD2's learning); `queue` is what comes after this
-- part, as JSON ([{"task": 12}, {"routine": 3}, {"label": "the car"}]), and `part` of
-- `parts` is where this one is in the run.
ALTER TABLE body_double_sessions ADD COLUMN queue TEXT;
ALTER TABLE body_double_sessions ADD COLUMN part INTEGER;
ALTER TABLE body_double_sessions ADD COLUMN parts INTEGER;
