-- CF2-CF9 (the Cooking Feedback Plan): notes left while cooking or on a recipe's page, the
-- fixes Themi keeps on its own side, and the changes written to the cookbook doc.

-- A note on a step (or one ingredient line). `kind` and what follows are the sort's (CF3).
-- status: new (not sorted yet), open (sorted, to decide at wrap-up), fixed (a display fix
-- applied, to acknowledge), reported (nothing to decide), waiting (Not now), done (written
-- to the recipe), kept (kept as a note), ok (a fix acknowledged), undone, stale (the
-- recipe's words moved on), failed.
CREATE TABLE cooking_notes (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES cooking_sessions(id) ON DELETE SET NULL,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    step_label TEXT NOT NULL DEFAULT '',
    step_index INTEGER,
    step_text TEXT NOT NULL DEFAULT '',
    line INTEGER,
    chip TEXT NOT NULL DEFAULT '',
    said TEXT NOT NULL DEFAULT '',
    how TEXT NOT NULL CHECK (how IN ('tap', 'typed', 'voice', 'page')),
    recipe_digest TEXT NOT NULL,
    shown TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    kind TEXT CHECK (kind IN ('display', 'change', 'note', 'other')),
    summary TEXT NOT NULL DEFAULT '',
    proposal TEXT NOT NULL DEFAULT '{}',
    bug_id INTEGER,
    fix_id INTEGER,
    edit_id INTEGER,
    status TEXT NOT NULL DEFAULT 'new',
    sorts INTEGER NOT NULL DEFAULT 0,
    decided_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    decided_at TEXT
);
CREATE INDEX cooking_notes_session ON cooking_notes (session_id);
CREATE INDEX cooking_notes_recipe ON cooking_notes (recipe_id, status);

-- A fix on Themi's side of how a recipe's step is shown (CF3 links; CF7 prep, timer; CF8
-- split). Ignored once the step's words no longer hash to `step_hash`.
CREATE TABLE recipe_fixes (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    step_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('links', 'prep', 'timer', 'split')),
    data TEXT NOT NULL,
    note_id INTEGER REFERENCES cooking_notes(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    undone_at TEXT
);
CREATE INDEX recipe_fixes_recipe ON recipe_fixes (recipe_id);

-- A change written to a recipe from a note (CF4): the ops, and the revisions around it.
CREATE TABLE cookbook_edits (
    id INTEGER PRIMARY KEY,
    note_id INTEGER REFERENCES cooking_notes(id) ON DELETE SET NULL,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    book TEXT NOT NULL DEFAULT '',
    ops TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    revision_before TEXT NOT NULL DEFAULT '',
    revision_after TEXT NOT NULL DEFAULT '',
    written_at TEXT NOT NULL,
    undone_at TEXT,
    undo_of INTEGER REFERENCES cookbook_edits(id) ON DELETE SET NULL
);
CREATE INDEX cookbook_edits_recipe ON cookbook_edits (recipe_id);

-- CF4: changing a recipe in the family's cookbook from a cooking note. A shared document is
-- written, nothing is spent or sent as anyone: Tier 1 to start, may become automatic.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('cookbook_edit', 'Change a recipe in the family cookbook', 'family', 2,
     '1970-01-01T00:00:00+00:00');
