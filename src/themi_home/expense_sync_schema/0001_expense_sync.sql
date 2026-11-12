-- EX4a: writing a person's expense sheets to Google Sheets is a side effect, so it goes
-- through the trust tiers: each person's own, asking first to start, and it may become
-- automatic (it spends no money and sends nothing as them).
INSERT INTO action_categories (name, label, scope, tier, max_tier, updated_at) VALUES
    ('expense_sheet_sync', 'Keep your expense sheets up to date in Google Sheets', 'member',
     1, 2, '1970-01-01T00:00:00+00:00');
