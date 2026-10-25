-- What Themi may do on its own. Tier 1 = staged for approval, Tier 2 = automatic.
-- An escalated category behaves as Tier 1 until someone resumes it.
CREATE TABLE action_categories (
    name TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('member', 'family')),
    tier INTEGER NOT NULL DEFAULT 1 CHECK (tier IN (1, 2)),
    max_tier INTEGER NOT NULL CHECK (max_tier IN (1, 2)),
    escalated INTEGER NOT NULL DEFAULT 0,
    escalation_reason TEXT,
    granted_by_rule INTEGER,
    updated_at TEXT NOT NULL,
    CHECK (tier <= max_tier)
);

INSERT INTO action_categories (name, label, scope, max_tier, updated_at) VALUES
    ('email_mark_read', 'Mark confirmation emails as read', 'member', 2, '1970-01-01T00:00:00+00:00'),
    ('email_archive_noise', 'Archive noise emails', 'member', 2, '1970-01-01T00:00:00+00:00'),
    ('grocery_list_add', 'Add items to the grocery list', 'family', 2, '1970-01-01T00:00:00+00:00'),
    ('calendar_write', 'Write calendar events', 'family', 2, '1970-01-01T00:00:00+00:00'),
    ('email_reply', 'Send an email reply', 'member', 1, '1970-01-01T00:00:00+00:00'),
    ('safeway_cart', 'Stage a Safeway cart', 'family', 1, '1970-01-01T00:00:00+00:00'),
    ('doordash_order', 'Stage a DoorDash order', 'family', 1, '1970-01-01T00:00:00+00:00'),
    ('vendor_call', 'Vendor call', 'member', 1, '1970-01-01T00:00:00+00:00'),
    ('habit_trial', 'Try a new habit or check-in', 'member', 1, '1970-01-01T00:00:00+00:00');

CREATE TABLE pending_actions (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL REFERENCES action_categories(name),
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    executor TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',           -- JSON
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'snoozed', 'executing', 'done', 'declined', 'failed', 'expired')),
    automatic INTEGER NOT NULL DEFAULT 0,         -- ran under Tier 2 without asking
    snoozed_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    result TEXT,
    resolved_by TEXT,                             -- 'member:3', 'system', 'rule:5'
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX pending_actions_member_status ON pending_actions (member_id, status);

-- Everything that happens to actions and categories. Append-only.
CREATE TABLE action_audit (
    id INTEGER PRIMARY KEY,
    action_id INTEGER,
    category TEXT NOT NULL,
    member_id INTEGER,
    event TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TRIGGER action_audit_no_update BEFORE UPDATE ON action_audit
BEGIN
    SELECT RAISE(ABORT, 'action_audit is append-only');
END;
CREATE TRIGGER action_audit_no_delete BEFORE DELETE ON action_audit
BEGIN
    SELECT RAISE(ABORT, 'action_audit is append-only');
END;
