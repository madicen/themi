-- F9c: a plan that steps up week by week ("1.3 miles, then 1.5, then up 0.25 a week, on
-- Tuesdays"), as JSON (see themi.core.progression). Its nudges say the week's amount.
ALTER TABLE tasks ADD COLUMN progression TEXT;
