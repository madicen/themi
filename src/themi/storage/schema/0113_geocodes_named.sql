-- F29e (bug #154): "parent's house" was found on the map near Oroville. Places named with
-- no street number are looked up in what the family told Themi first now; the cached map
-- answers for such phrases go, and are looked up again if still needed.
DELETE FROM geocodes WHERE query_key NOT GLOB '*[0-9]*';
