-- 30: the washer and dryer, read from LG ThinQ. The family's one personal access token,
-- encrypted, for the country it was made for; the client id is made once and kept (LG
-- blocks callers that keep making new ones).
CREATE TABLE thinq_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    token BLOB NOT NULL,                          -- encrypted
    country TEXT NOT NULL,                        -- ISO code: picks LG's regional server
    client_id TEXT NOT NULL,
    linked_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL
);
