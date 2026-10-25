-- Small key/value settings that don't deserve their own table.
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Encrypted credentials that belong to the household as a whole
-- (per-member credentials live with their member records).
CREATE TABLE app_secrets (
    name TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
