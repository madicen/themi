-- 31: the laundry. How long a wet load stays fresh, and how long the washer's rinse takes.
ALTER TABLE family ADD COLUMN laundry_fresh_hours REAL NOT NULL DEFAULT 8;
ALTER TABLE family ADD COLUMN laundry_rinse_minutes INTEGER NOT NULL DEFAULT 30;

-- A load the washer finished: wet until the dryer starts (dried), a new wash starts
-- (superseded), or someone says it's handled (done). Past the fresh hours it's offered a
-- rinse, timed to finish as that person's next good window begins.
CREATE TABLE laundry_loads (
    id INTEGER PRIMARY KEY,
    washer_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    finished_at TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('wet', 'dried', 'superseded', 'done')),
    rescue_at TEXT,                               -- when it went past fresh
    rinse_from TEXT,                              -- the rinse suggested: start...
    ready_at TEXT,                                -- ...and finish
    closed_at TEXT
);
CREATE INDEX laundry_loads_wet ON laundry_loads (status);
CREATE INDEX laundry_loads_task ON laundry_loads (task_id);
