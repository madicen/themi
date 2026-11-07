-- F34k (idea #177): a call before the business closes. The hours of a place to phone, looked
-- up once (a near-home web search) or said in chat, by place, so a correction is remembered
-- for it. hours: JSON {"0": ["08:00", "17:00"], ..., "6": null}, Monday first; null is closed.
CREATE TABLE place_hours (
    place_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hours TEXT,  -- NULL: looked for and not found
    phone TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',  -- a link, or 'said in chat'
    updated_at TEXT NOT NULL
);

-- Which place a call task is for, and whether "I couldn't find their hours" was said.
CREATE TABLE task_places (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    place_key TEXT NOT NULL,
    told_unknown INTEGER NOT NULL DEFAULT 0
);

-- One closing-time nudge per task per day.
CREATE TABLE closing_nudges (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (task_id, day)
);
