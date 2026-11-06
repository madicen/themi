"""F33a: a tool that changes something inside Themi says what it did (`Done`), and when
that was in their own words, the line is the turn's answer (reply 237)."""

from typing import Any

from tests.fixtures.family import SeededFamily
from themi.ai.types import ToolCall
from themi.core.tools import Done, ToolContext, ToolRegistry, in_their_words, tool


@tool("remove_thing", "Remove a thing", {"title": {"type": "string"}})
async def remove_thing(ctx: ToolContext, args: dict[str, Any]) -> Done:
    said = f'Removed "{args["title"]}".'
    return Done(said, asked=in_their_words(ctx, args["title"]))


async def run(family: SeededFamily, wrote: str, title: str) -> tuple[ToolContext, str]:
    ctx = ToolContext(family.erin, object(), request_text=wrote)  # type: ignore[arg-type]
    result = await ToolRegistry([remove_thing]).run(
        ToolCall("c1", "remove_thing", {"title": title}), ctx
    )
    return ctx, result.content


async def test_done_in_their_words_is_the_answer(family: SeededFamily) -> None:
    ctx, content = await run(family, "Remove the refill cat feeders", "Refill cat feeders")
    assert content == 'Removed "Refill cat feeders".'
    assert ctx.asked == ctx.replies == ['Removed "Refill cat feeders".']
    assert ctx.outcomes == ["ok"]


async def test_done_the_model_inferred_is_left_to_the_model(family: SeededFamily) -> None:
    ctx, content = await run(family, "Remove the regular cat feeders", "Refill cat feeders")
    assert content == 'Removed "Refill cat feeders".'  # the model still reads it
    assert ctx.asked == [] and ctx.replies == []


def test_in_their_words(family: SeededFamily) -> None:
    def ctx(wrote: str) -> ToolContext:
        return ToolContext(family.erin, object(), request_text=wrote)  # type: ignore[arg-type]

    assert in_their_words(ctx("took my vitamins!"), "Vitamins")
    assert not in_their_words(ctx("I took my meds"), "Take Meds")  # "take" isn't "took"
    assert in_their_words(ctx("turn off the TV"), "TV")  # only short words: the whole name
    assert not in_their_words(ctx("turn it off"), "TV")
