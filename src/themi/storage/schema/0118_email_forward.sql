-- F31d (idea #168): forwarding an email. It sends as the person, so it always asks first.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('email_forward', 'Forward an email for you', 'member', 1, '1970-01-01T00:00:00+00:00');
