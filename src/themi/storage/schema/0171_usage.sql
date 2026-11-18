-- UC1 (the Themi Usage Plan): each meter's daily totals, kept 400 days, and the limits an
-- admin set in place of a module's defaults. `day` is in the meter's reset zone; `scope` is
-- an id (a backend's, a device's) or empty, never a name.
CREATE TABLE usage_daily (
    day TEXT NOT NULL,
    meter TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, meter, scope, model)
);
CREATE INDEX usage_daily_meter ON usage_daily (meter, day);
CREATE TABLE usage_limits (
    meter TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    per_day REAL,
    per_month REAL,
    set_by TEXT NOT NULL,
    set_at TEXT NOT NULL,
    PRIMARY KEY (meter, scope)
);
