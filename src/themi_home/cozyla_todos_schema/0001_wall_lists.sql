-- CR21b: which of Themi's lists the wall keeps, and the wall's copy of each item, in place
-- of lists.cozyla_list_id and wall_name, and list_items.cozyla_todo_id, wall_title and
-- wall_done, which are left as they were and no longer read.
CREATE TABLE wall_lists (
    list_id INTEGER PRIMARY KEY REFERENCES lists(id) ON DELETE CASCADE,
    cozyla_list_id TEXT NOT NULL UNIQUE,
    wall_name TEXT
);
INSERT INTO wall_lists (list_id, cozyla_list_id, wall_name)
    SELECT id, cozyla_list_id, wall_name FROM lists WHERE cozyla_list_id IS NOT NULL;
CREATE TABLE wall_list_items (
    item_id INTEGER PRIMARY KEY REFERENCES list_items(id) ON DELETE CASCADE,
    todo_id TEXT NOT NULL,
    title TEXT,
    done INTEGER
);
INSERT INTO wall_list_items (item_id, todo_id, title, done)
    SELECT id, cozyla_todo_id, wall_title, wall_done FROM list_items
    WHERE cozyla_todo_id IS NOT NULL;
