-- PT6a: what the wall, the morning message and chat say about a parcel. `signature`: a
-- carrier says someone has to sign for it. `moved_from`: the day it was due before its
-- carrier moved it later (the wall says "now due Friday" on that day); empty otherwise.
ALTER TABLE parcels ADD COLUMN signature INTEGER NOT NULL DEFAULT 0;
ALTER TABLE parcels ADD COLUMN moved_from TEXT NOT NULL DEFAULT '';
