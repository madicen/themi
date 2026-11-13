"""CR1: the module contract, its loader and context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily, seed_family
from themi.accounts import AccountStore
from themi.modules import Module, ModuleContext, ModuleError, order
from themi.scheduler import Scheduler
from themi.standard.breaks import Breaks, BreaksModule
from themi.standard.reactions import Reactions, ReactionsModule
from themi.standard.wrong_replies import WrongReplies, WrongRepliesModule


def make(name: str, requires: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> Module:
    log: list[str] = []

    class M(Module):
        def install(self, ctx: ModuleContext) -> None:
            log.append(name)

    M.name = name
    M.requires = requires
    M.optional = optional
    return M()


def names(modules: list[Module]) -> list[str]:
    return [m.name for m in modules]


def test_order_keeps_the_given_order_when_nothing_requires_otherwise() -> None:
    assert names(order([make("c"), make("a"), make("b")])) == ["c", "a", "b"]


def test_a_requirement_comes_first_and_the_rest_keep_their_places() -> None:
    mods = [make("reminders", ("tasks",)), make("lists"), make("tasks")]
    assert names(order(mods)) == ["tasks", "reminders", "lists"]


def test_an_optional_module_comes_first_only_when_present() -> None:
    assert names(order([make("triage", optional=("gmail",)), make("gmail")])) == [
        "gmail",
        "triage",
    ]
    assert names(order([make("triage", optional=("gmail",))])) == ["triage"]


def test_a_missing_requirement_names_both_modules() -> None:
    with pytest.raises(ModuleError, match="pantry requires groceries"):
        order([make("pantry", ("groceries",))])


def test_a_requirement_installed_earlier_counts() -> None:
    assert names(order([make("pantry", ("groceries",))], installed=["groceries"])) == ["pantry"]


def test_a_loop_is_refused_with_its_path() -> None:
    with pytest.raises(ModuleError, match="a -> b -> a"):
        order([make("a", ("b",)), make("b", ("a",))])


def test_a_name_twice_is_refused() -> None:
    with pytest.raises(ModuleError, match="tasks is listed twice"):
        order([make("tasks"), make("tasks")])
    with pytest.raises(ModuleError, match="listed twice"):
        order([make("tasks")], installed=["tasks"])


def test_a_module_needs_a_name() -> None:
    class Nameless(Module):
        pass

    with pytest.raises(ModuleError, match="Nameless has no name"):
        order([Nameless()])


def test_a_module_without_install_says_so(family: SeededFamily) -> None:
    class Empty(Module):
        name = "empty"

    with pytest.raises(NotImplementedError, match="empty"):
        ModuleContext(bare_services(family.store)).load(Empty())


def test_provide_get_and_maybe(family: SeededFamily) -> None:
    ctx = ModuleContext(bare_services(family.store))

    class Thing:
        pass

    class Other:
        pass

    thing = ctx.provide(Thing())
    assert ctx.get(Thing) is thing
    assert ctx.maybe(Other) is None
    with pytest.raises(ModuleError, match="Other, which no installed module provides"):
        ctx.get(Other)
    with pytest.raises(ModuleError, match="Thing is provided twice"):
        ctx.provide(Thing())


def test_the_error_names_the_module_that_asked(family: SeededFamily) -> None:
    class Wanted:
        pass

    class Asker(Module):
        name = "asker"

        def install(self, ctx: ModuleContext) -> None:
            ctx.get(Wanted)

    with pytest.raises(ModuleError, match="module asker asked for Wanted"):
        ModuleContext(bare_services(family.store)).load(Asker())


def test_jobs_are_collected_and_a_name_twice_is_refused(family: SeededFamily) -> None:
    ctx = ModuleContext(bare_services(family.store))

    async def run() -> None:
        return None

    ctx.periodic("tasks.resurface", timedelta(minutes=15), run)
    assert [(j.name, j.every) for j in ctx.jobs] == [("tasks.resurface", timedelta(minutes=15))]
    with pytest.raises(ModuleError, match=r"tasks\.resurface is added twice"):
        ctx.periodic("tasks.resurface", timedelta(hours=1), run)


async def test_a_modules_jobs_wait_for_the_family_and_the_cores_do_not(
    store: AccountStore,
) -> None:
    ran: list[str] = []

    def job(name: str) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            ran.append(name)

        return run

    class Wall(Module):
        name = "wall"

        def install(self, ctx: ModuleContext) -> None:
            ctx.periodic("wall.sync", timedelta(minutes=1), job("wall.sync"))

    ctx = ModuleContext(bare_services(store))
    ctx.periodic("outbox.flush", timedelta(seconds=30), job("outbox.flush"))
    ctx.load(Wall())
    for j in ctx.jobs:
        await j.run()
    assert ran == ["outbox.flush"]  # no family yet: nobody for the wall to act for
    seed_family(store)
    for j in ctx.jobs:
        await j.run()
    assert ran == ["outbox.flush", "outbox.flush", "wall.sync"]


def test_the_scheduler_is_there_only_when_given(family: SeededFamily) -> None:
    with pytest.raises(ModuleError, match="needs the scheduler"):
        _ = ModuleContext(bare_services(family.store)).scheduler
    scheduler = Scheduler(family.db)
    assert ModuleContext(bare_services(family.store), scheduler=scheduler).scheduler is scheduler


def test_load_can_be_called_again_and_remembers_what_is_installed(family: SeededFamily) -> None:
    ctx = ModuleContext(bare_services(family.store))
    ctx.load(make("tasks"))
    ctx.load(make("reminders", ("tasks",)))
    assert ctx.installed == ["tasks", "reminders"]
    assert ctx.has("tasks") and not ctx.has("lists")


def test_a_button_prefix_twice_is_refused(family: SeededFamily) -> None:
    ctx = ModuleContext(bare_services(family.store))

    async def handler(event: object) -> None:
        return None

    ctx.button("break", handler)  # type: ignore[arg-type]
    with pytest.raises(ModuleError, match="button prefix break is taken"):
        ctx.button("break", handler)  # type: ignore[arg-type]


# ----- the first three modules, each installed alone ---------------------------------


def test_breaks_installs_alone(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ctx = ModuleContext(services)
    ctx.load(BreaksModule())
    assert isinstance(ctx.get(Breaks), Breaks)
    assert "/break" in services.commands and "break" in services.button_handlers
    assert services.tools.get("start_break") and services.tools.get("end_break")


def test_reactions_and_wrong_replies_install_alone(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ctx = ModuleContext(services)
    ctx.load(ReactionsModule(), WrongRepliesModule())
    assert isinstance(ctx.get(Reactions), Reactions)
    assert isinstance(ctx.get(WrongReplies), WrongReplies)
    assert [h.__qualname__ for h in services.reaction_handlers] == [
        "Reactions.on_reaction",
        "WrongReplies.on_reaction",
    ]


# ----- CR3: the registry on Services ----------------------------------------------------


def test_services_files_objects_under_their_class_name(family: SeededFamily) -> None:
    from themi.core import keys
    from themi.standard.lists import Lists

    services = bare_services(family.store)
    lists = Lists(services)
    services.provide(Lists, lists)
    assert services.get(Lists) is lists
    assert services.maybe(keys.lists) is lists  # a key names the same class
    assert services.provided() == ["Lists"]


def test_providing_none_takes_it_away_and_get_then_says_so(family: SeededFamily) -> None:
    from themi.core import keys

    services = bare_services(family.store)

    class FakeTriage:
        pass

    services.provide(keys.triage, FakeTriage())  # type: ignore[arg-type]  # a test double
    assert services.maybe(keys.triage) is not None
    services.provide(keys.triage, None)
    assert services.maybe(keys.triage) is None
    with pytest.raises(ModuleError, match="nothing provides EmailTriage"):
        services.get(keys.triage)


def test_the_context_and_services_share_one_registry(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ctx = ModuleContext(services)
    breaks = ctx.load(BreaksModule()) and ctx.get(Breaks)
    assert services.get(Breaks) is breaks


def test_every_key_names_a_class_the_full_app_provides() -> None:
    """A key whose name matches nothing would always find None, silently."""
    import inspect

    from themi.core import keys
    from themi.modules.registry import Key

    found = {name: k for name, k in vars(keys).items() if isinstance(k, Key)}
    assert len(found) == 73  # 35a: takeout; F26c: task_parts; EX1a-EX4a: expense sheets; WX1; DC1
    source = inspect.getsource(keys)
    for attr, key in found.items():
        assert f"import {key.name}\n" in source, f"keys.{attr} names {key.name}, never imported"
