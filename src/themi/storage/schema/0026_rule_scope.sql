-- Personal rules (F2): a locked personal rule only goes into the AI requests of
-- the person it affects. Every existing rule stays a household rule.
ALTER TABLE rules ADD COLUMN scope TEXT NOT NULL DEFAULT 'household'
    CHECK (scope IN ('household', 'personal'));
