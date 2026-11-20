-- F50b (bug #232): amounts in other currencies. A day's exchange rate, asked once; an
-- email's currency and the amount as written ("HK$816.00") when it isn't dollars, with
-- amount_cents then in dollars (or NULL when there was no rate).
CREATE TABLE exchange_rates (
    day TEXT NOT NULL,
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    rate REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (day, base, quote)
);
ALTER TABLE emails ADD COLUMN currency TEXT;
ALTER TABLE emails ADD COLUMN amount_original TEXT;
-- Confirmations whose amount was read as dollars but whose summary shows another
-- currency: read again (ExpectedEmails.recheck_amounts) and left out of the usual meanwhile.
UPDATE emails SET currency = 'recheck'
WHERE category = 'confirmation' AND amount_cents IS NOT NULL AND (
    summary LIKE '%HK$%' OR summary LIKE '%CA$%' OR summary LIKE '%C$%'
    OR summary LIKE '%A$%' OR summary LIKE '%NZ$%' OR summary LIKE '%NT$%'
    OR summary LIKE '%MX$%' OR summary LIKE '%S$%' OR summary LIKE '%R$%'
    OR summary LIKE '%€%' OR summary LIKE '%£%' OR summary LIKE '%¥%' OR summary LIKE '%₹%'
    OR summary LIKE '% EUR%' OR summary LIKE '% GBP%' OR summary LIKE '% CAD%'
    OR summary LIKE '% AUD%' OR summary LIKE '% HKD%' OR summary LIKE '% CHF%'
);
