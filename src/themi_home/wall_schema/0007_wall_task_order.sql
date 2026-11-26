-- F64i (idea #274): a person's own order for their chores and to-dos on the wall, set by
-- dragging on their page. Ranked tasks come first in this order; the rest follow by the
-- wall's own rule (due first, then important, then soonest).
CREATE TABLE wall_task_order (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    PRIMARY KEY (member_id, task_id)
);
