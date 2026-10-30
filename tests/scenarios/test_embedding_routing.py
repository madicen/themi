"""P7b: with THEMI_TOOL_ROUTING=embeddings, groups are chosen by meaning as well as by the
word lists, through the AI router (keys, fallback), and the groups used lately stay."""

from __future__ import annotations

import pytest

from tests.fakes.embedder import TopicEmbedder
from tests.scenarios.harness import Scenario
from themi.ai.embeddings import VectorCache
from themi.core.routing import EmbeddingRouter
from themi.core.tools import GROUP_EXAMPLES, choose_groups
from themi.storage.db import Database

# The fake model's topics: the settings examples say "rest" or "break", the pantry ones
# "dinner", "cook" or "fridge"; the messages below say "lie down" and "nap".
TOPICS = TopicEmbedder(
    {
        "settings": ("rest", "break", "lie down", "nap", "taking five"),
        "pantry": ("dinner", "cook", "fridge", "lunch"),
    }
)


@pytest.fixture
def embedding(scenario: Scenario) -> Scenario:
    scenario.app.services.tool_routing = "embeddings"
    scenario.primary.embed_with = TOPICS
    return scenario


def chats(scenario: Scenario) -> list[set[str]]:
    return [set(r.tool_names) for r in scenario.primary.requests if r.op == "chat"]


async def test_a_paraphrase_the_word_lists_miss_brings_its_group(embedding: Scenario) -> None:
    said = "Going to lie down for half an hour"
    assert "settings" not in choose_groups([said])
    embedding.primary.queue_text("Rest well.")
    await embedding.say("Erin", said)
    assert {"start_break", "pause_messages"} <= chats(embedding)[-1]


async def test_two_asks_bring_two_groups(embedding: Scenario) -> None:
    embedding.primary.queue_text("Okay.")
    await embedding.say("Erin", "Need a nap, then what can we have tonight? Too tired to cook")
    assert {"start_break", "suggest_meals"} <= chats(embedding)[-1]


async def test_a_message_about_nothing_in_particular_brings_nothing_more(
    embedding: Scenario,
) -> None:
    embedding.primary.queue_text("Morning!")
    await embedding.say("Erin", "Good morning")
    assert not chats(embedding)[-1] & {"start_break", "suggest_meals"}


async def test_a_failing_embedder_leaves_the_word_lists_to_decide(scenario: Scenario) -> None:
    scenario.app.services.tool_routing = "embeddings"  # and neither model can embed
    scenario.primary.queue_text("Rest well.")
    assert await scenario.say("Erin", "Going to lie down for half an hour") == ["Rest well."]
    assert "start_break" not in chats(scenario)[-1]
    scenario.primary.queue_text("Enjoy it.")
    await scenario.say("Erin", "I'm taking a break")  # the word lists still work
    assert "start_break" in chats(scenario)[-1]


async def test_a_slow_embedder_leaves_the_word_lists_to_decide(embedding: Scenario) -> None:
    embedding.primary.take(3)  # the embedding call: over the second it's allowed
    embedding.primary.queue_text("Rest well.")
    assert await embedding.say("Erin", "Going to lie down for half an hour") == ["Rest well."]
    assert "start_break" not in chats(embedding)[-1]


async def test_embedding_falls_back_to_the_next_backend(scenario: Scenario) -> None:
    scenario.app.services.tool_routing = "embeddings"
    scenario.primary.fail(1, status=401, op="embed")  # a bad key: skip to the fallback
    scenario.fallback.embed_with = TOPICS
    scenario.primary.queue_text("Rest well.")
    await scenario.say("Erin", "Going to lie down for half an hour")
    assert "start_break" in chats(scenario)[-1]
    assert any(r.op == "embed" for r in scenario.fallback.requests)
    calls = scenario.app.db.query("SELECT task, member_id FROM ai_calls WHERE task = 'embedding'")
    assert calls and {c["member_id"] for c in calls} == {scenario.member("Erin").id}


async def test_groups_used_lately_stay_for_a_short_follow_up(embedding: Scenario) -> None:
    embedding.primary.queue_tool_call(
        "update_pantry", {"items": [{"name": "eggs", "status": "out", "expiry": ""}]}
    )
    embedding.primary.queue_text("Noted.")
    await embedding.say("Erin", "We're out of eggs")
    embedding.primary.queue_text("Noted.")
    await embedding.say("Erin", "and butter")
    assert {"show_pantry", "suggest_meals"} <= chats(embedding)[-1]


async def test_the_examples_are_embedded_once_and_kept_across_restarts(
    embedding: Scenario,
) -> None:
    examples = {e for group in GROUP_EXAMPLES.values() for e in group}

    def embedded() -> list[str]:
        return [t for r in embedding.primary.requests if r.op == "embed" for t in r.texts]

    for said in ("Going to lie down for half an hour", "Need a nap"):
        embedding.primary.queue_text("Rest well.")
        await embedding.say("Erin", said)
    assert sorted(t for t in embedded() if t in examples) == sorted(examples)  # once each

    # A restart: a new router on the same database reads the examples from the cache.
    db: Database = embedding.app.db
    group_router = embedding.app.services.group_router
    assert group_router is not None
    router = EmbeddingRouter(group_router.embedder, VectorCache(db))
    before = len(embedded())
    assert await router.choose(embedding.member("Erin").id, ["Going to lie down"]) == {"settings"}
    assert embedded()[before:] == ["Going to lie down"]


async def test_the_last_messages_are_not_embedded_again(embedding: Scenario) -> None:
    # The free tier counts every text as a request; the person's last two go each time.
    for said in ("Going to lie down for half an hour", "Need a nap", "Off for a quick rest"):
        embedding.primary.queue_text("Okay.")
        await embedding.say("Erin", said)
    messages = [
        t
        for r in embedding.primary.requests
        if r.op == "embed"
        for t in r.texts
        if t not in {e for group in GROUP_EXAMPLES.values() for e in group}
    ]
    assert messages == ["Going to lie down for half an hour", "Need a nap", "Off for a quick rest"]
