-- E2 (Erin's idea #50): senders and emails triage isn't sure about wait in an audit, one
-- task per person, gone through one at a time: urgent, important, both or neither.
CREATE TABLE email_audit_items (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES linked_accounts (id) ON DELETE CASCADE,
    email_id INTEGER REFERENCES emails (id) ON DELETE CASCADE,  -- NULL: about the sender
    address TEXT NOT NULL,
    label TEXT NOT NULL,
    reason TEXT NOT NULL,
    suggestion_id INTEGER REFERENCES sender_suggestions (id),
    created_at TEXT NOT NULL,
    answer TEXT CHECK (answer IN ('urgent', 'important', 'both', 'neither')),
    answered_at TEXT
);
CREATE UNIQUE INDEX email_audit_sender ON email_audit_items (account_id, address)
    WHERE email_id IS NULL;
CREATE UNIQUE INDEX email_audit_email ON email_audit_items (email_id) WHERE email_id IS NOT NULL;
CREATE TABLE email_audits (
    member_id INTEGER PRIMARY KEY REFERENCES members (id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks (id),
    started_at TEXT
);
-- Senders suggested before (E1's messages) and never answered wait in the audit now.
INSERT INTO email_audit_items (member_id, account_id, address, label, reason, suggestion_id,
                               created_at)
SELECT la.member_id, s.account_id, lower(s.address), s.label, 'suggested before', MIN(s.id),
       MIN(s.offered_at)
FROM sender_suggestions s JOIN linked_accounts la ON la.id = s.account_id
WHERE s.added_at IS NULL
GROUP BY s.account_id, lower(s.address);
