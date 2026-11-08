-- SP2: what admins set on the Modules page. A module's secrets live here, encrypted with
-- the secret key (its plain settings go to themi.toml). The draft is the one set of
-- changes waiting for a restart: JSON, its secrets encrypted inside it.
CREATE TABLE module_secrets (
    module TEXT NOT NULL,
    field TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    set_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    set_at TEXT NOT NULL,
    PRIMARY KEY (module, field)
);

CREATE TABLE config_drafts (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    body TEXT NOT NULL,
    updated_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);
