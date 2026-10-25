-- Senders that always count as urgent for this inbox: addresses or @domains (JSON list).
ALTER TABLE linked_accounts ADD COLUMN urgent_senders TEXT NOT NULL DEFAULT '[]';

-- Triage state per email. `initial` mail (found by a first sync) is sorted but
-- never acted on: it's up to a week old.
ALTER TABLE emails ADD COLUMN initial INTEGER NOT NULL DEFAULT 0;
ALTER TABLE emails ADD COLUMN triage_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (triage_status IN ('pending', 'done'));
ALTER TABLE emails ADD COLUMN triage_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE emails ADD COLUMN category TEXT
    CHECK (category IN ('urgent', 'confirmation', 'receipt', 'needs_reply', 'routine', 'noise'));
ALTER TABLE emails ADD COLUMN urgent_kind TEXT;   -- tenant, financial, property, family, other
ALTER TABLE emails ADD COLUMN summary TEXT;       -- one line, from triage
ALTER TABLE emails ADD COLUMN triaged_at TEXT;
CREATE INDEX emails_triage ON emails (triage_status, id);
