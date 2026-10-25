-- What each member's energy is usually like at each hour of the week (0 = Monday 00:00
-- local, 167 = Sunday 23:00). Learned from outcomes in prompt 19; until a cell has data,
-- a gentle prior day-curve stands in.
CREATE TABLE energy_baseline (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    hour_of_week INTEGER NOT NULL CHECK (hour_of_week BETWEEN 0 AND 167),
    mean REAL NOT NULL CHECK (mean BETWEEN 0 AND 100),
    n INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (member_id, hour_of_week)
);
