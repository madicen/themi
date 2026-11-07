-- F34gb: an OpenAI-compatible backend can say it sees pictures (Claude and Gemini always
-- do, Cloudflare never). And Michael, 2026-11-07: 100 pictures in chat a day, not 30.
ALTER TABLE ai_backends ADD COLUMN supports_images INTEGER NOT NULL DEFAULT 0;
UPDATE members SET picture_daily_cap = 100 WHERE picture_daily_cap = 30;
