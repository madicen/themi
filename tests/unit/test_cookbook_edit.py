"""CF3/CF4: a recipe change as ops anchored on the recipe's words: applied, refused when the
words aren't there, and undone."""

from __future__ import annotations

import pytest

from themi_home.cookbook import Line
from themi_home.cookbook_edit import Op, Rejected, Shape, apply, undo_ops

SHAPE = Shape(
    [Line("1 onion", ""), Line("1 tsp cumin", "Spices"), Line("1 tsp salt", "Spices")],
    [Line("Fry the onion."), Line("Add the spices and chickpeas and simmer 10 minutes."),
     Line("Serve.")],
    ["Recipe Notes: good with rice"],
)  # fmt: skip


def texts(shape: Shape) -> tuple[list[str], list[str], list[str]]:
    return ([i.text for i in shape.ingredients], [s.text for s in shape.steps], shape.notes)


@pytest.mark.parametrize(
    "ops",
    [
        [Op("split_step", "Add the spices and chickpeas and simmer 10 minutes.",
            new=("Add the spices and chickpeas.", "Simmer 10 minutes."))],
        [Op("replace_step", "Serve.", new=("Serve with rice.",))],
        [Op("merge_steps", olds=("Fry the onion.", "Add the spices and chickpeas and simmer 10 "
                                 "minutes.")  , new=("Fry the onion, then add the rest.",))],
        [Op("insert_step", after="Fry the onion.", new=("Toast the spices.",))],
        [Op("insert_step", new=("Soak the chickpeas.",))],
        [Op("remove_step", "Serve.")],
        [Op("replace_line", "1 tsp salt", new=("½ tsp salt",))],
        [Op("insert_line", new=("1 tsp paprika",), group="Spices")],
        [Op("insert_line", after="1 onion", new=("2 cloves garlic",))],
        [Op("remove_line", "1 tsp cumin")],
        [Op("add_note", new=("Note: less salt (cooked Oct 21)",))],
        [Op("split_step", "Serve.", new=("Plate it.", "Serve.")),
         Op("replace_line", "1 onion", new=("2 onions",))],
    ],
)  # fmt: skip
def test_every_op_applies_and_undoes(ops: list[Op]) -> None:
    changed, done = apply(ops, SHAPE)
    assert texts(changed) != texts(SHAPE)
    back, _ = apply(undo_ops(done), changed)
    assert texts(back) == texts(SHAPE)
    assert [i.group for i in back.ingredients] == ["", "Spices", "Spices"]


def test_groups_are_kept() -> None:
    changed, _ = apply(
        [
            Op("insert_line", new=("1 tsp paprika",), group="Spices"),
            Op("replace_line", "1 tsp cumin", new=("2 tsp cumin",)),
        ],
        SHAPE,
    )
    assert [(i.text, i.group) for i in changed.ingredients] == [
        ("1 onion", ""), ("2 tsp cumin", "Spices"), ("1 tsp salt", "Spices"),
        ("1 tsp paprika", "Spices")]  # fmt: skip


@pytest.mark.parametrize(
    "ops",
    [
        [Op("replace_step", "Bake for an hour.", new=("Bake 70 minutes.",))],  # never said
        [Op("split_step", "Serve.", new=("Serve.",))],  # a split into one
        [Op("merge_steps", olds=("Fry the onion.", "Serve."), new=("x",))],  # not one after another
        [Op("remove_line", "1 cup flour")],
        [Op("remove_note", "Note: nothing like this")],
        [],
    ],
)  # fmt: skip
def test_ops_that_dont_fit_are_refused(ops: list[Op]) -> None:
    with pytest.raises(Rejected):
        apply(ops, SHAPE)


def test_an_unknown_op_is_refused() -> None:
    with pytest.raises(Rejected):
        Op.from_json({"op": "rewrite_everything", "new": ["x"]})
    assert Op.from_json({"op": "replace_step", "old": "  Serve. ", "new": ["Plate  it."]}) == Op(
        "replace_step", "Serve.", new=("Plate it.",))  # fmt: skip
