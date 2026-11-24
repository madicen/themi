-- F60b (bug #261): what the family told Themi a litter box's code means, as the CatGenie app
-- shows it ("Error: Drainage issue"). Read after the codes in
-- themi_home.connectors.catgenie.events.CODES, which are never relearned.
CREATE TABLE litter_codes (
    code TEXT PRIMARY KEY,
    words TEXT NOT NULL,             -- "a drainage issue": after "it's showing"
    member_id INTEGER REFERENCES members (id) ON DELETE SET NULL,
    said_at TEXT NOT NULL
);
