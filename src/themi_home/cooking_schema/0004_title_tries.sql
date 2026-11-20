-- F50d: a recipe whose titles call failed, and how many times, for these words. It's tried
-- again by the background job, three times at most; titles stored stay final as before.
CREATE TABLE cooking_title_tries (
    recipe_id INTEGER PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    tries INTEGER NOT NULL,
    tried_at TEXT NOT NULL
);
