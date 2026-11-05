-- F28c (idea #144): the pages each person keeps on the website's menu bar, in order, as a
-- JSON list of paths ("/", "/tasks", "/spending"); at most four, with More always after
-- them. NULL is the usual bar: Home, Tasks, Lists.
ALTER TABLE members ADD COLUMN menu_bar TEXT;
