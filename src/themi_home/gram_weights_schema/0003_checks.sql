-- GW6: the family's own guide lines, checked once for each wording: "fine", "asked" (a
-- question went out), "kept" (they said Keep: never asked again for these words).
CREATE TABLE gram_weights_checked (
    line TEXT NOT NULL,
    part INTEGER NOT NULL,          -- which weight on the line (two on "1 Cup / 1 Tbsp ...")
    state TEXT NOT NULL CHECK (state IN ('fine', 'asked', 'kept')),
    checked_at TEXT NOT NULL,
    PRIMARY KEY (line, part)
);
