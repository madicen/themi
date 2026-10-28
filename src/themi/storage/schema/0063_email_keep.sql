-- F15c (bug #53): "the Schwab email is urgent and shouldn't be archived" puts it back in
-- the inbox when Themi archived it. Asked for in their words, it runs at once.
INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('email_keep', 'Put an email back in the inbox', 'member', 2, '1970-01-01T00:00:00+00:00');
