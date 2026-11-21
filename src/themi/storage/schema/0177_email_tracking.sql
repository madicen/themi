-- PT1: the tracking numbers found in an email (its whole text and its link addresses), as
-- JSON: [{"carrier": "ups", "number": "1Z..."}]. Only the numbers: the links themselves
-- carry a shop's click-tracking tokens and aren't kept.
ALTER TABLE emails ADD COLUMN tracking TEXT NOT NULL DEFAULT '[]';
