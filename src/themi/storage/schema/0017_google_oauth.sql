-- The Google address a member signs in to the website with (optional).
ALTER TABLE members ADD COLUMN email TEXT;
CREATE UNIQUE INDEX members_email ON members (lower(email)) WHERE email IS NOT NULL;

-- One row per Google sign-in or linking attempt in flight. The state is what the
-- browser carries; only its hash is kept. The PKCE verifier is encrypted.
CREATE TABLE oauth_states (
    state_hash TEXT PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('signin', 'link')),
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    code_verifier BLOB NOT NULL,                   -- encrypted
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
