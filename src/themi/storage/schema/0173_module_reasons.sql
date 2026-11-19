-- MP2: why each module turned on from the Modules page is on: "asked", or "needed by
-- <module>" when it came on for another. Kept past restarts so turning that other module
-- off can offer to turn it off too. Template modules have no row: they count as asked.
CREATE TABLE module_reasons (
    module TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
