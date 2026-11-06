-- RC2b: how a grocery card was scaled, as they said it ("double", "for 6").
ALTER TABLE recipe_cards ADD COLUMN scale_said TEXT NOT NULL DEFAULT '';
