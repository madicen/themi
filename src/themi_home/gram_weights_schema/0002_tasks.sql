-- GW4: the weighing task for a weight nobody could find online, while it's open.
ALTER TABLE gram_weights_meta ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL;
