-- F38c: how a card ended ("declined by the 👎", or the action's status), kept on its outbox
-- row so `themi feedback` can say it for a reply marked through its card. approval_messages
-- rows go once the card is edited, so the outbox row is what's left.
ALTER TABLE outbox ADD COLUMN card_outcome TEXT;
