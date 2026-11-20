-- WL4: ticking things off on the wall. A tap is the person's own decision, so it's
-- automatic from the start; it's in the audit like every other action.
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('wall_tap', 'Tick things off on the wall', 'family', 2, 2, '1970-01-01T00:00:00+00:00');
