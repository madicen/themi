"""CR10b1: the Google pack's tool groups (see themi.core.groups)."""

from __future__ import annotations

from themi.core.tools import ToolGroup

EMAIL = ToolGroup(
    name="email",
    description=("inboxes, expected emails, time-sensitive and important senders, the email audit"),
    words=(
        "e-?mail|inbox|gmail|sender|expect|bill|statement|confirmation|unsubscribe|au"
        "dit|time.sensitive|archive|noise|junk|spam|mark(?:ed)? (?:as )?read|forward"
    ),
    examples=(
        "Is there anything in my inbox I should see?",
        "Archive the promotional emails",
        "Get rid of the newsletters in my inbox",
        "Mail from my accountant is always urgent",
        "Treat the store emails as low priority",
        "Don't archive that email from the landlord",
        "I'm waiting for a package tracking email",
        "Which emails are you watching for?",
        "Forget about the receipt email, it came",
        "Start watching my personal inbox too",
        "Let's sort out which senders matter",
        "Any unread emails that need a reply?",
        "Forward that email to Erin",
        "Send this email to jenn@example.com",
        "Can Michael see the email from the HOA?",
    ),
    tools=(
        "expect_email",
        "list_expected_emails",
        "forget_expected_email",
        "set_urgent_senders",
        "set_inbox_watched",
        "inbox_setup",
        "keep_email",
        "start_email_audit",
        "set_sender_levels",
        "archive_noise_emails",
        "forward_email",
    ),
    order=70,
)
