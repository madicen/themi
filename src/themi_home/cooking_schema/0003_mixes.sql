-- CK15b: mixes made for a recipe (music as settings, `music_mix.Mix.to_data()`), by kind, so
-- the same recipe gets the same mix next time. Oldest first is the one it starts with.
CREATE TABLE music_mixes (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX music_mixes_recipe ON music_mixes (recipe_id, kind);
