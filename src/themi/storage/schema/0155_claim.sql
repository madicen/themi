-- SP7a: claiming a new Themi from its website. One code at a time, kept as a hash; a few
-- wrong tries lock it for a while. `key_saved_at`: the claimant said they saved the secret
-- key Themi made, so the page that shows it doesn't again.
CREATE TABLE claim (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    used_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    wrong_tries INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    key_saved_at TEXT
);
