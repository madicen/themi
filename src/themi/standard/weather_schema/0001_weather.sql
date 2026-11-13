-- WX1: the forecast at home, one row per day it was fetched on (refreshed each hour).
-- Yesterday's row is kept; older ones are pruned.
CREATE TABLE weather_forecasts (
    day TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    forecast TEXT NOT NULL,
    alerts TEXT NOT NULL DEFAULT '[]'
);
