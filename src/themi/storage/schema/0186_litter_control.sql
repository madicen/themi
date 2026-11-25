-- F63b (Erin's idea #268): Themi can work the CatGenie, not just read it. Starting or stopping
-- a clean, and changing its settings, go through this category: asked each time to start
-- with, and may become automatic.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('litter_box_control', 'Start or stop the litter box''s clean, or change its settings',
     'family', 1, 2, '1970-01-01T00:00:00+00:00');

-- An error's "Try a clean": when it was tapped and by whom, and how it went once the box
-- finished that clean ('cleared', 'back', or 'none' when it never cleaned).
ALTER TABLE litter_problems ADD COLUMN retried_at TEXT;
ALTER TABLE litter_problems ADD COLUMN retried_by INTEGER REFERENCES members (id) ON DELETE SET NULL;
ALTER TABLE litter_problems ADD COLUMN retry_outcome TEXT;
