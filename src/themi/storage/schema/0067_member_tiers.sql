-- F16a (bug #58, idea #62): a category that is each person's own (scope 'member': their
-- email, their calendar, their routines) becomes automatic per person, only for whoever
-- locked the rule. Household categories keep `action_categories.tier`.
CREATE TABLE member_tiers (
    category TEXT NOT NULL REFERENCES action_categories(name),
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    granted_by_rule INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (category, member_id)
);

CREATE TRIGGER member_tiers_not_capped BEFORE INSERT ON member_tiers
WHEN (SELECT max_tier FROM action_categories WHERE name = NEW.category) < 2
    OR (SELECT scope FROM action_categories WHERE name = NEW.category) != 'member'
BEGIN
    SELECT RAISE(ABORT, 'that category can''t be automatic per person');
END;

-- A personal category that is automatic now stays so only for the person whose rule did it.
INSERT INTO member_tiers (category, member_id, granted_by_rule, created_at)
SELECT c.name, r.affects, c.granted_by_rule, c.updated_at
FROM action_categories c JOIN rules r ON r.id = c.granted_by_rule
WHERE c.scope = 'member' AND c.tier = 2 AND r.affects IS NOT NULL;
UPDATE action_categories SET tier = 1, granted_by_rule = NULL WHERE scope = 'member';

-- Their grants are personal rules: only in their own conversations.
UPDATE rules SET scope = 'personal'
WHERE kind = 'autonomy_grant'
  AND category IN (SELECT name FROM action_categories WHERE scope = 'member');
