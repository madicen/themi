-- F65j (bug #275): the family's own order for the shared list on the wall (Either of you and
-- Family to-do), set by dragging on the Together page, as a person's is (0007).
CREATE TABLE wall_family_order (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL
);
