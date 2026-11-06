-- RC5: adding a recipe someone liked to the family cookbook doc. A shared document is
-- written, nothing is spent or sent as anyone: Tier 1 to start, may become automatic.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('cookbook_add', 'Add a recipe to the family cookbook', 'family', 2, '1970-01-01T00:00:00+00:00');
