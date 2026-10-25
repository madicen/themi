import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM, InvalidValue, PermissionDenied
from themi.ai.settings import (
    DEFAULT_BACKEND_LABEL,
    AISettingsStore,
    AITask,
    RouteEntry,
)
from themi.storage.secrets import Cipher, Secret, generate_key


@pytest.fixture
def ai(family: SeededFamily) -> AISettingsStore:
    return AISettingsStore(family.db, Cipher(generate_key()))


def test_backends_hide_their_keys(family: SeededFamily, ai: AISettingsStore) -> None:
    erin = family.erin
    claude = ai.add_backend(erin, erin.id, "Claude", "anthropic", api_key=Secret("sk-ant-erin"))
    local = ai.add_backend(erin, erin.id, "Desktop Ollama", "ollama", model="qwen3:14b")
    assert claude.has_key and not local.has_key
    assert "sk-ant-erin" not in repr(claude)
    assert [b.label for b in ai.backends(erin.id)] == ["Claude", "Desktop Ollama"]
    raw = family.db.scalar("SELECT api_key FROM ai_backends WHERE id = ?", (claude.id,))
    assert b"sk-ant-erin" not in raw


def test_ai_settings_are_self_service_only(family: SeededFamily, ai: AISettingsStore) -> None:
    with pytest.raises(PermissionDenied):
        ai.add_backend(family.erin, family.husband.id, "Claude", "anthropic")
    mine = ai.add_backend(family.husband, family.husband.id, "Claude", "anthropic")
    with pytest.raises(PermissionDenied):
        ai.update_backend(family.erin, mine.id, model="claude-sonnet-5-5")
    with pytest.raises(PermissionDenied):
        ai.remove_backend(family.erin, mine.id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "watson"},
        {"kind": "anthropic", "timeout": 0},
        {"kind": "anthropic", "effort": "extreme"},
        {"kind": "anthropic", "label": "  "},
    ],
)
def test_backend_values_are_validated(
    family: SeededFamily, ai: AISettingsStore, kwargs: dict
) -> None:
    label = kwargs.pop("label", "X")
    with pytest.raises(InvalidValue):
        ai.add_backend(family.erin, family.erin.id, label, **kwargs)


def test_labels_are_unique_per_member(family: SeededFamily, ai: AISettingsStore) -> None:
    ai.add_backend(family.erin, family.erin.id, "Claude", "anthropic")
    with pytest.raises(InvalidValue, match="already have"):
        ai.add_backend(family.erin, family.erin.id, "Claude", "anthropic")
    ai.add_backend(family.husband, family.husband.id, "Claude", "anthropic")  # fine for him


def test_defaults_are_gemini_free_tier(family: SeededFamily, ai: AISettingsStore) -> None:
    ai.ensure_defaults(family.erin.id)
    ai.ensure_defaults(family.erin.id)  # idempotent
    (backend,) = ai.backends(family.erin.id)
    assert backend.label == DEFAULT_BACKEND_LABEL and backend.kind == "gemini"
    assert backend.supports_audio and not backend.has_key
    for task in AITask:
        (entry,) = ai.resolve(family.erin.id, task)
        assert entry.config.resolved_model == "gemini-3.5-flash-lite"
    assert ai.backends(family.husband.id) == []


def test_chains_resolve_in_order_with_keys_and_model_overrides(
    family: SeededFamily, ai: AISettingsStore
) -> None:
    erin = family.erin
    claude = ai.add_backend(
        erin, erin.id, "Claude", "anthropic", api_key=Secret("k1"), effort="low"
    )
    gemini = ai.add_backend(erin, erin.id, "Gemini", "gemini", api_key=Secret("k2"))
    ai.set_chain(
        erin,
        erin.id,
        AITask.CONVERSATION,
        [RouteEntry(claude.id, "claude-sonnet-5-5"), RouteEntry(gemini.id)],
    )
    first, second = ai.resolve(erin.id, AITask.CONVERSATION)
    assert (first.label, first.config.kind, first.config.model) == (
        "Claude",
        "anthropic",
        "claude-sonnet-5-5",
    )
    assert first.config.api_key == Secret("k1") and first.config.effort == "low"
    assert (second.label, second.config.resolved_model) == ("Gemini", "gemini-3.5-flash-lite")
    assert ai.resolve(erin.id, AITask.EMAIL_TRIAGE) == []


def test_chain_rules(family: SeededFamily, ai: AISettingsStore) -> None:
    erin, husband = family.erin, family.husband
    mine = ai.add_backend(erin, erin.id, "Claude", "anthropic")
    his = ai.add_backend(husband, husband.id, "Claude", "anthropic")
    with pytest.raises(InvalidValue):
        ai.set_chain(erin, erin.id, AITask.CONVERSATION, [])
    with pytest.raises(InvalidValue, match="only once"):
        ai.set_chain(erin, erin.id, AITask.CONVERSATION, [RouteEntry(mine.id), RouteEntry(mine.id)])
    with pytest.raises(PermissionDenied):
        ai.set_chain(erin, erin.id, AITask.CONVERSATION, [RouteEntry(his.id)])
    with pytest.raises(PermissionDenied):
        ai.set_chain(husband, erin.id, AITask.CONVERSATION, [RouteEntry(mine.id)])


def test_removing_a_backend_closes_the_gap_in_chains(
    family: SeededFamily, ai: AISettingsStore
) -> None:
    erin = family.erin
    a = ai.add_backend(erin, erin.id, "A", "anthropic")
    b = ai.add_backend(erin, erin.id, "B", "gemini")
    c = ai.add_backend(erin, erin.id, "C", "ollama", model="m")
    ai.set_chain(
        erin, erin.id, AITask.CONVERSATION, [RouteEntry(a.id), RouteEntry(b.id), RouteEntry(c.id)]
    )
    ai.remove_backend(erin, b.id)
    assert ai.chain(erin.id, AITask.CONVERSATION) == [RouteEntry(a.id), RouteEntry(c.id)]
    positions = family.db.query(
        "SELECT position FROM ai_routes WHERE member_id = ? ORDER BY position", (erin.id,)
    )
    assert [p["position"] for p in positions] == [0, 1]


def test_updating_and_clearing_keys(family: SeededFamily, ai: AISettingsStore) -> None:
    erin = family.erin
    backend = ai.add_backend(erin, erin.id, "Claude", "anthropic", api_key=Secret("old"))
    ai.set_chain(erin, erin.id, AITask.CONVERSATION, [RouteEntry(backend.id)])
    ai.update_backend(erin, backend.id, api_key=Secret("new"), model="claude-opus-5", timeout=30)
    (entry,) = ai.resolve(erin.id, AITask.CONVERSATION)
    assert entry.config.api_key == Secret("new")
    assert (entry.config.model, entry.config.timeout) == ("claude-opus-5", 30)
    ai.update_backend(erin, backend.id, label="Claude (work)")  # key untouched
    assert ai.get_backend(backend.id).has_key
    assert not ai.clear_key(erin, backend.id).has_key
    with pytest.raises(InvalidValue):
        ai.update_backend(erin, backend.id, colour="blue")


def test_member_deletion_removes_ai_settings(family: SeededFamily, ai: AISettingsStore) -> None:
    ai.ensure_defaults(family.husband.id)
    family.store.delete_member(SYSTEM, family.husband.id)
    assert family.db.scalar("SELECT COUNT(*) FROM ai_backends") == 0
    assert family.db.scalar("SELECT COUNT(*) FROM ai_routes") == 0
