-- F61c (bug #267): a backend's model the provider says isn't found (a 404: a preview model
-- retired). The router skips it until the model is changed, and the admin is told once.
CREATE TABLE ai_models_gone (
    backend_id INTEGER NOT NULL REFERENCES ai_backends (id) ON DELETE CASCADE,
    model TEXT NOT NULL,             -- as the backend was asked for it ("" for its default)
    found_at TEXT NOT NULL,
    PRIMARY KEY (backend_id, model)
);
