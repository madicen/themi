-- SP7b: passkeys for admins who don't use Telegram (so /site can't send them a link), and
-- a recovery code each, kept as a hash, that works once. Challenges are the server's half
-- of a passkey ceremony, for five minutes, found by a token in a cookie.
CREATE TABLE passkeys (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    credential_id BLOB NOT NULL UNIQUE,
    public_key BLOB NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE recovery_codes (
    member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE passkey_challenges (
    token_hash TEXT PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('register', 'sign_in')),
    challenge BLOB NOT NULL,
    expires_at TEXT NOT NULL
);
