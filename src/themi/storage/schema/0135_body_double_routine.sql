-- F34h: a session can go through one of their routines; each step done ticks its item.
ALTER TABLE body_double_sessions ADD COLUMN routine_id INTEGER REFERENCES routines(id) ON DELETE SET NULL;
