-- F41a, bug #197: the Whoosh reports its sani-solution as cleans left, not a percent.
-- `sani_unit` is '%' or 'cleans', as `sani_left` was read.
ALTER TABLE litter_states ADD COLUMN sani_unit TEXT NOT NULL DEFAULT '%';
