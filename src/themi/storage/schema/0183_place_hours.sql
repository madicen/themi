-- F58e (bug #251): a saved place's hours by weekday, as `place_hours` keeps a shop's:
-- JSON {"0": ["18:30", "20:30"], ..., "6": null} (Monday first; null closed), or '' for
-- none said. Nothing is copied from the notes: the family says them once more.
ALTER TABLE places ADD COLUMN hours TEXT NOT NULL DEFAULT '';
