-- DC4: a message can carry a picture, drawn when it goes (`picture`: a registered picture's
-- name, "day_card"). `picture_sent`: the message went as that picture with its text as the
-- caption, so an edit changes the caption, not the text.
ALTER TABLE outbox ADD COLUMN picture TEXT;
ALTER TABLE outbox ADD COLUMN picture_sent INTEGER NOT NULL DEFAULT 0;
