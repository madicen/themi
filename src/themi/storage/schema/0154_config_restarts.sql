-- SP6: restarts asked for on the Modules page. `config_last_good` is the setup before the
-- last one applied (themi.toml as text, and the module secrets as they were, still
-- encrypted), for "go back to the last working setup". `config_restarts` says who asked and
-- what changed, so they hear how it went once Themi is back.
CREATE TABLE config_last_good (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    toml TEXT NOT NULL,
    secrets TEXT NOT NULL,                        -- JSON: [[module, field, ciphertext], ...]
    saved_at TEXT NOT NULL
);

CREATE TABLE config_restarts (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    changes TEXT NOT NULL,                        -- JSON: what the draft's log said
    asked_at TEXT NOT NULL,
    announced_at TEXT
);
