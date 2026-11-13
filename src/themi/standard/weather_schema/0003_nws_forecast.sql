-- WX4: NWS's forecast stands in when Open-Meteo can't be reached (US homes only).
-- `grid_url`: NWS's raw forecast grid for the home (from `points`, NULL until asked).
-- `nws_until`: after an Open-Meteo failure, NWS is the source until this time (UTC ISO).
-- `source`: which service a stored forecast came from.
ALTER TABLE weather_home ADD COLUMN grid_url TEXT;
ALTER TABLE weather_home ADD COLUMN nws_until TEXT;
ALTER TABLE weather_forecasts ADD COLUMN source TEXT NOT NULL DEFAULT 'open-meteo';
