-- F39a, bug #194: feeding a pet now from its feeder (Tuya's manual_feed). Asked in so many
-- words, that's the person's yes; a rule can make it automatic.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('pet_feed', 'Feed a pet from its feeder', 'family', 2, '1970-01-01T00:00:00+00:00');
