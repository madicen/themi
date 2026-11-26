-- RC8c: what a recipe says to have out ("Tools": cheesecloth, molds), kept apart from its
-- ingredients so it never goes on the grocery list; and why it isn't ready to cook as
-- written ("not converted yet", from a "Dairy Recipes to Convert" section).
ALTER TABLE recipes ADD COLUMN tools TEXT NOT NULL DEFAULT '[]';
ALTER TABLE recipes ADD COLUMN draft TEXT NOT NULL DEFAULT '';
