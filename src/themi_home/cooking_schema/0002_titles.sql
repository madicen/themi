-- CK12: a short title for each step of a recipe ("Sauté mushrooms"), for the cook screen's
-- step strip. They come with the prep call and are kept until the recipe's words change.
CREATE TABLE cooking_titles (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (recipe_id, hash)
);
