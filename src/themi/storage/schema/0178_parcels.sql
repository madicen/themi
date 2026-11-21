-- PT2: one row per parcel, by its tracking number, fed by every email that names it (and by
-- the carriers' answers, PT5). Replaces WL8's row per email (`deliveries`).
--
-- `number` is empty for a parcel no email has given a number for yet; `carrier` is "ups",
-- "usps", "fedex" or "amazon", several space-separated while two carriers' patterns both
-- fit the number (settled by the first lookup), or empty. Only the shop's name, never
-- what's in the parcel: the wall is a shared screen and a parcel can be a present.
-- `expected_day` is the household's local date it's due, or the day it came once
-- delivered; empty when no one has said. `updated_at` is when the newest fact was true
-- (an email's arrival, a carrier's scan), and an older fact never overwrites a newer one.
CREATE TABLE parcels (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    carrier TEXT NOT NULL DEFAULT '',
    number TEXT NOT NULL DEFAULT '',
    shop TEXT NOT NULL,
    shop_key TEXT NOT NULL,
    status TEXT NOT NULL,
    expected_day TEXT NOT NULL DEFAULT '',
    window_start TEXT NOT NULL DEFAULT '',
    window_end TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL DEFAULT '',
    delivered_at TEXT,
    left_at TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'email',
    updated_at TEXT NOT NULL,
    checked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX parcels_number ON parcels (number) WHERE number != '';
CREATE INDEX parcels_day ON parcels (expected_day);
CREATE INDEX parcels_shop ON parcels (shop_key);

-- WL8's rows, as numberless parcels: one per shop and day, the furthest along.
INSERT INTO parcels (member_id, shop, shop_key, status, expected_day, source, updated_at,
                     created_at)
SELECT MIN(member_id), MIN(shop), lower(shop),
       CASE MAX(CASE status WHEN 'delivered' THEN 3 WHEN 'out_for_delivery' THEN 2 ELSE 1 END)
           WHEN 3 THEN 'delivered' WHEN 2 THEN 'out_for_delivery' ELSE 'on_the_way' END,
       day, 'email', MAX(found_at), MIN(found_at)
FROM deliveries
GROUP BY lower(shop), day;

DROP TABLE deliveries;
