-- WA2: what's been tapped on a wall alert (We're off, Quiet, Not going, Got it), so every
-- frame and a reload agree. A key names one alert: one event at one start, or one timer.
CREATE TABLE wall_alert_answers (
    alert_key TEXT NOT NULL,
    answer TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (alert_key, answer)
);
