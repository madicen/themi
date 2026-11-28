"""F65b (bug #282, reply 620): a longer answer to Themi's "Is it done?" is read with it."""

from __future__ import annotations

from themi.core.which_task import Said, answers, texts_to_score, which

TITLES = {155: "Weigh one rounded tsp onion powder", 160: "Weigh 1 cup of dried mushrooms"}
QUESTION = (
    '"Weigh one rounded tsp onion powder" is still open: I couldn\'t tell that\'s the one you '
    "meant. Is it done?"
)
ANSWER = "Yes, that one's done, but also the crushed pepper is done too."


def test_a_yes_of_any_length_is_an_answer() -> None:
    assert answers(ANSWER) and answers("Yep") and answers("that one's done as well, thanks")
    assert not answers("I weighed the crushed peppercorns and they're eight grams")


def test_the_question_is_scored_with_a_long_yes() -> None:
    said = Said(ANSWER, said_before=QUESTION)
    assert texts_to_score(said, TITLES) == [ANSWER, QUESTION]


def test_a_long_yes_names_what_the_question_named() -> None:
    sims = {ANSWER: {155: 0.4, 160: 0.38}, QUESTION: {155: 0.9, 160: 0.5}}
    assert which(Said(ANSWER, said_before=QUESTION), TITLES, sims) == {155}


def test_and_what_it_names_itself() -> None:
    answer = "Yes, and the mushrooms are done too"
    sims = {answer: {155: 0.3, 160: 0.8}, QUESTION: {155: 0.9, 160: 0.5}}
    assert which(Said(answer, said_before=QUESTION), TITLES, sims) == {155, 160}


def test_a_long_message_that_isnt_an_answer_reads_only_itself() -> None:
    text = "I weighed the crushed peppercorns and they're eight grams"
    sims = {text: {155: 0.3, 160: 0.35}}
    assert which(Said(text, said_before=QUESTION), TITLES, sims) == frozenset()
