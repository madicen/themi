-- What the household has. Names are lowercased and single-spaced ("olive oil").
CREATE TABLE pantry_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'plenty' CHECK (status IN ('plenty', 'low', 'out')),
    -- how the status was learned: nothing yet, someone said so, a receipt, a prediction,
    -- or ticking it off the list
    status_source TEXT NOT NULL DEFAULT 'new'
        CHECK (status_source IN ('new', 'said', 'receipt', 'predicted', 'list')),
    staple INTEGER NOT NULL DEFAULT 0,
    expiry TEXT,                                   -- YYYY-MM-DD, when known
    updated_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Purchase history, mostly from receipt emails. Kept if the email is forgotten.
CREATE TABLE purchases (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES pantry_items(id) ON DELETE CASCADE,
    email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    vendor TEXT NOT NULL DEFAULT '',
    quantity TEXT NOT NULL DEFAULT '',
    price_cents INTEGER,
    purchased_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX purchases_item ON purchases (item_id, purchased_at);

-- Themi's grocery list: the source of truth. OurGroceries mirrors it.
CREATE TABLE grocery_list (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'needed' CHECK (status IN ('needed', 'bought', 'removed')),
    pantry_item_id INTEGER REFERENCES pantry_items(id) ON DELETE SET NULL,
    added_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    action_id INTEGER REFERENCES pending_actions(id) ON DELETE SET NULL,
    added_at TEXT NOT NULL,
    done_at TEXT,
    -- the mirror: 'pending' until OurGroceries matches this row's status
    mirror_state TEXT NOT NULL DEFAULT 'pending' CHECK (mirror_state IN ('pending', 'done')),
    mirror_attempts INTEGER NOT NULL DEFAULT 0,
    mirror_after TEXT,
    mirror_error TEXT
);
CREATE UNIQUE INDEX grocery_list_needed ON grocery_list (name) WHERE status = 'needed';
CREATE INDEX grocery_list_mirror ON grocery_list (mirror_state, mirror_after);

-- Receipts are read into purchases once; a few tries if the AI is unavailable.
ALTER TABLE emails ADD COLUMN receipt_parsed_at TEXT;
ALTER TABLE emails ADD COLUMN receipt_attempts INTEGER NOT NULL DEFAULT 0;
