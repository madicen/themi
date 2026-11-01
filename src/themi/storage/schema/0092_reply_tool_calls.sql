-- F20a (bug #110): what each tool call was given and what it said back, redacted and cut
-- short, so a bug report can show why a turn went the way it did. Kept as long as the reply.
ALTER TABLE reply_tools ADD COLUMN arguments TEXT;
ALTER TABLE reply_tools ADD COLUMN result TEXT;
