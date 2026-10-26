-- Bug #15: a one-off task can live on the wall's chore chart instead of its to-do list.
ALTER TABLE tasks ADD COLUMN on_chart INTEGER NOT NULL DEFAULT 0;
