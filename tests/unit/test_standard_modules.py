"""CR2a: each standard module installs on the core alone, with what it requires."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi.modules import Module, ModuleContext
from themi.standard.burnout import Burnout, BurnoutModule
from themi.standard.business_hours import BusinessHours, BusinessHoursModule
from themi.standard.checkin_reviews import CheckinReviews, CheckinReviewsModule
from themi.standard.commands import Commands, CommandsModule
from themi.standard.conversation_mode import ConversationMode, ConversationModeModule
from themi.standard.day_summary import DaySummary, DaySummaryModule
from themi.standard.feedback import FeedbackChat, FeedbackModule
from themi.standard.focus import Focus, FocusModule
from themi.standard.follow_ups import FollowUps, FollowUpsModule
from themi.standard.guides import Guides, GuidesModule
from themi.standard.habits import HabitReserve, HabitsModule
from themi.standard.journal import Journal, JournalModule
from themi.standard.lists import Lists, ListsModule
from themi.standard.memory import Memory, MemoryModule
from themi.standard.reminders import Reminders, RemindersModule
from themi.standard.routines import Routines, RoutinesModule
from themi.standard.taking import Taking, TakingModule
from themi.standard.tasks import TaskBoard, TasksModule
from themi.standard.web_search import WebSearch, WebSearchModule
from themi_home.liaison import Liaison, LiaisonModule
from themi_home.which_list import WhichList, WhichListModule

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
    return module_context(family.store)


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
