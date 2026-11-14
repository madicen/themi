-- F43b (idea #208): the wall's icon for each linked chore, as last read, so pictures show
-- the emoji the wall does without asking the wall each time.
ALTER TABLE cozyla_chores ADD COLUMN icon TEXT;
