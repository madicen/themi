-- F52a: how the frame shows the wall, as its page last said: 'fullscreen' (an installed
-- app), 'fullscreen-api' (a Chrome tab made full screen by a touch), 'standalone' or
-- 'browser'. NULL until the frame's page says.
ALTER TABLE wall_devices ADD COLUMN display TEXT;
