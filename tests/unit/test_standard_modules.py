"""CR2a: each standard module installs on the core alone, with what it requires."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily
from themi.core.burnout import Burnout, BurnoutModule
from themi.core.business_hours import BusinessHours, BusinessHoursModule
from themi.core.checkin_reviews import CheckinReviews, CheckinReviewsModule
from themi.core.commands import Commands, CommandsModule
from themi.core.conversation_mode import ConversationMode, ConversationModeModule
from themi.core.day_summary import DaySummary, DaySummaryModule
from themi.core.feedback import FeedbackChat, FeedbackModule
from themi.core.focus import Focus, FocusModule
from themi.core.follow_ups import FollowUps, FollowUpsModule
from themi.core.guides import Guides, GuidesModule
from themi.core.habits import HabitReserve, HabitsModule
from themi.core.journal import Journal, JournalModule
from themi.core.liaison import Liaison, LiaisonModule
from themi.core.lists import Lists, ListsModule
from themi.core.memory import Memory, MemoryModule
from themi.core.reminders import Reminders, RemindersModule
from themi.core.routines import Routines, RoutinesModule
from themi.core.rules import Rulebook
from themi.core.taking import Taking, TakingModule
from themi.core.tasks import TaskBoard, TasksModule
from themi.core.web_search import WebSearch, WebSearchModule
from themi.core.which_list import WhichList, WhichListModule
from themi.energy import EnergyModel
from themi.modules import Module, ModuleContext
from themi.scheduler import Scheduler

# module, what it provides, the modules it needs first, the jobs it adds
CASES: list[tuple[Callable[[], Module], type, list[Callable[[], Module]], set[str]]] = [
    (TasksModule, TaskBoard, [], {"tasks.resurface", "tasks.schedules"}),
    (FollowUpsModule, FollowUps, [TasksModule], set()),
    (RemindersModule, Reminders, [TasksModule], {"tasks.day_end", "tasks.overdue"}),
    (BusinessHoursModule, BusinessHours, [TasksModule], {"tasks.closing"}),
    (DaySummaryModule, DaySummary, [TasksModule], {"calendar.morning"}),
    (FocusModule, Focus, [TasksModule, DaySummaryModule], set()),
    (TakingModule, Taking, [TasksModule], set()),
    (GuidesModule, Guides, [], set()),
    (ListsModule, Lists, [], set()),
    (WhichListModule, WhichList, [], set()),
    (BurnoutModule, Burnout, [TasksModule], {"burnout.hand_over"}),
    (ConversationModeModule, ConversationMode, [], set()),
    (CheckinReviewsModule, CheckinReviews, [], {"checkins.reviews"}),
    (HabitsModule, HabitReserve, [], {"habits.offer", "habits.send"}),
    (RoutinesModule, Routines, [], {"routines.check"}),
    (JournalModule, Journal, [], {"memory.journal"}),
    (MemoryModule, Memory, [], set()),
    (FeedbackModule, FeedbackChat, [], {"feedback.forget_pictures"}),
    (CommandsModule, Commands, [], set()),
    (LiaisonModule, Liaison, [], set()),
    (lambda: WebSearchModule(None), WebSearch, [], set()),
]


def core_context(family: SeededFamily) -> ModuleContext:
    services = bare_services(family.store)
    ctx = ModuleContext(services, scheduler=Scheduler(family.db))
    ctx.provide(EnergyModel(family.store))  # core, until it's a module
    ctx.provide(Rulebook(services.autonomy, services.outbox))
    return ctx


@pytest.mark.parametrize(
    ("make", "provides", "needs", "jobs"), CASES, ids=[c[1].__name__ for c in CASES]
)
def test_the_module_installs_alone(
    family: SeededFamily,
    make: Callable[[], Module],
    provides: type,
    needs: list[Callable[[], Module]],
    jobs: set[str],
) -> None:
    ctx = core_context(family)
    ctx.load(*(n() for n in needs))
    before = {job.name for job in ctx.jobs}
    module = make()
    ctx.load(module)
    assert ctx.has(module.name)
    assert isinstance(ctx.get(provides), provides)
    assert {job.name for job in ctx.jobs} - before == jobs


def test_a_module_without_what_it_requires_is_refused(family: SeededFamily) -> None:
    from themi.modules import ModuleError

    with pytest.raises(ModuleError, match="reminders requires tasks"):
        core_context(family).load(RemindersModule())
