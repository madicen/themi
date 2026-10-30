-- GT1a: items taken from each linked account's Google Tasks (its default list, which
-- "Hey Google, add a task" fills). handled: answered, not yet deleted at Google; removed:
-- deleted there; waiting: no AI backend answered, tried again after retry_after.
CREATE TABLE google_task_inbox (
    account_id INTEGER NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    text TEXT NOT NULL,                           -- what the agent was given
    status TEXT NOT NULL CHECK (status IN ('handled', 'removed', 'waiting')),
    retry_after TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, task_id)
);
