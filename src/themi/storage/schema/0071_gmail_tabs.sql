-- Michael's unread mail (2026-10-29): Gmail labels mail CATEGORY_UPDATES even when the
-- Updates tab is turned off and it shows in Primary. Which tabs an account really shows,
-- learned from Gmail's own "category:primary" search: {"CATEGORY_UPDATES": false, ...}
-- (false: shows in Primary). A label not in it is taken to be a tab, as before.
ALTER TABLE linked_accounts ADD COLUMN gmail_tabs TEXT;
ALTER TABLE linked_accounts ADD COLUMN gmail_tabs_checked_at TEXT;
