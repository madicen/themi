-- G1: OurGroceries syncs both ways. Each row keeps its OurGroceries item id once
-- known, and says where it came from.
ALTER TABLE grocery_list ADD COLUMN remote_id TEXT;
ALTER TABLE grocery_list ADD COLUMN source TEXT NOT NULL DEFAULT 'themi'
    CHECK (source IN ('themi', 'ourgroceries'));
CREATE INDEX grocery_list_remote ON grocery_list (remote_id);

-- What the list looked like at the last sync, so the next one can tell what
-- changed in the app since. Kept per list name: a different configured list
-- starts over with a first import instead of looking like everything was deleted.
CREATE TABLE ourgroceries_seen (
    list_name TEXT NOT NULL,
    remote_id TEXT NOT NULL,
    value TEXT NOT NULL,
    crossed_off INTEGER NOT NULL,
    PRIMARY KEY (list_name, remote_id)
);
CREATE TABLE ourgroceries_sync (
    list_name TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL
);
