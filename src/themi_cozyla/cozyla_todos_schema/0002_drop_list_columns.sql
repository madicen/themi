-- CR21d: 0001 copied the wall's lists and items into wall_lists and wall_list_items; the
-- old columns go.
ALTER TABLE lists DROP COLUMN cozyla_list_id;
ALTER TABLE lists DROP COLUMN wall_name;
ALTER TABLE list_items DROP COLUMN cozyla_todo_id;
ALTER TABLE list_items DROP COLUMN wall_title;
ALTER TABLE list_items DROP COLUMN wall_done;
