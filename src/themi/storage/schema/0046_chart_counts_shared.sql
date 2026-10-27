-- C2d follow-up: each person decides whether chores for either of you count toward their
-- chart limit (on: they wait their turn like the rest; off: they always show).
ALTER TABLE members ADD COLUMN chart_counts_shared INTEGER NOT NULL DEFAULT 1;
