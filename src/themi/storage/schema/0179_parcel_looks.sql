-- PT5: when a parcel should next be looked up regardless of its usual pace: set when an
-- email brings news of it (a "shipped" email is looked up straight away), cleared by the
-- look. `checked_at` (0178) is when it was last looked up.
ALTER TABLE parcels ADD COLUMN look_after TEXT;
