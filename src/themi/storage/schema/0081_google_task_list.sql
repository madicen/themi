-- GT1b: each person's open one-off tasks on a "Themi" list in their Google Tasks. The list
-- per linked account, and the Google id of every task Themi wrote there: an id it doesn't
-- know is a new item, handled as the inbox does (GT1a).
CREATE TABLE google_task_lists (
    account_id INTEGER PRIMARY KEY REFERENCES linked_accounts(id) ON DELETE CASCADE,
    list_id TEXT NOT NULL
);
CREATE TABLE google_task_links (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    google_id TEXT NOT NULL,
    removed INTEGER NOT NULL DEFAULT 0,           -- deleted in Google: not put back
    PRIMARY KEY (task_id, account_id),
    UNIQUE (account_id, google_id)
);

-- New items on the "Themi" list are handled as the inbox's are, so the inbox remembers
-- which list each came from.
ALTER TABLE google_task_inbox ADD COLUMN list_id TEXT NOT NULL DEFAULT '@default';
