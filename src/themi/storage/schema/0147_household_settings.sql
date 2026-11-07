-- CR7c: the household's settings that belong to one module, one row per setting, the
-- value as JSON. The takeout budget, the staples and the laundry times move here from
-- `family`; 0148 drops the moved columns.
CREATE TABLE household_settings (
    module TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (module, key)
);

INSERT INTO household_settings (module, key, value, updated_at)
SELECT 'spending', 'takeout_budget_cents', json(takeout_budget_cents), datetime('now')
FROM family;
INSERT INTO household_settings (module, key, value, updated_at)
SELECT 'pantry', 'staples', json(staples), datetime('now') FROM family;
INSERT INTO household_settings (module, key, value, updated_at)
SELECT 'thinq', 'laundry_fresh_hours', json(laundry_fresh_hours), datetime('now') FROM family;
INSERT INTO household_settings (module, key, value, updated_at)
SELECT 'thinq', 'laundry_rinse_minutes', json(laundry_rinse_minutes), datetime('now')
FROM family;
