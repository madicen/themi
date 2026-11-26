-- F64e (idea #270): several recipes on the go at once. The one in front has the highest
-- `front` (a counter: started, switched to, tapped forward); the rest are set aside as they were.
ALTER TABLE cooking_sessions ADD COLUMN front INTEGER NOT NULL DEFAULT 0;
