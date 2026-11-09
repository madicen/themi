-- F37c (Michael's idea #188): a sender whose offers of one kind (a card's category, such as
-- calendar_from_email) someone has asked Themi to stop. Their other mail is triaged as
-- before, and the other person still gets that sender's offers.
CREATE TABLE email_sender_skips (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    address TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (member_id, address, category)
);
