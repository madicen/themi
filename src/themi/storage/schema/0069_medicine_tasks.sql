-- Rx1 (Erin's idea #48): a medicine task never becomes done on a "not sure", and its nudge
-- asks "Taken already, or later?" with [Not sure]. Marked from the title, or when said.
ALTER TABLE tasks ADD COLUMN medicine INTEGER NOT NULL DEFAULT 0;
-- The title's whole words, as `tasks.MEDICINE` reads them ("Tabletop" isn't a tablet).
UPDATE tasks SET medicine = 1 WHERE id IN (
    SELECT id FROM (
        SELECT id, ' ' || replace(replace(replace(replace(lower(title), '-', ' '), ',', ' '),
               '.', ' '), '/', ' ') || ' ' AS t
        FROM tasks
    )
    WHERE t LIKE '% pill %'
   OR t LIKE '% pills %'
   OR t LIKE '% meds %'
   OR t LIKE '% medicine %'
   OR t LIKE '% medicines %'
   OR t LIKE '% medication %'
   OR t LIKE '% medications %'
   OR t LIKE '% wegovy %'
   OR t LIKE '% ozempic %'
   OR t LIKE '% insulin %'
   OR t LIKE '% inhaler %'
   OR t LIKE '% inhalers %'
   OR t LIKE '% tablet %'
   OR t LIKE '% tablets %'
   OR t LIKE '% capsule %'
   OR t LIKE '% capsules %'
   OR t LIKE '% prescription %'
   OR t LIKE '% prescriptions %'
   OR t LIKE '% dose %'
   OR t LIKE '% doses %'
   OR t LIKE '% tab %'
   OR t LIKE '% tabs %'
);
