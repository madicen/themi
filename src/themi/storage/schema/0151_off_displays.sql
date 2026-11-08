-- CR21a: "keep off the wall" becomes "keep off shared displays", whatever display a
-- Themi has (Themi's own reminders, the robot's and the washer's passing tasks).
ALTER TABLE tasks RENAME COLUMN off_wall TO off_displays;
