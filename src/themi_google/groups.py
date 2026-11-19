"""MP1: the Google pack's groups on the Modules page (the core's are in themi.modules.groups)."""

from __future__ import annotations

from themi.modules.groups import ModuleGroup

EMAIL = ModuleGroup(
    "email",
    "Email",
    "Gmail read and sorted: what matters, what's expected, and what's noise.",
    100,
)
CALENDAR = ModuleGroup(
    "calendar",
    "Calendar",
    "Google Calendar, busy times, time for tasks and travel times.",
    110,
    starter=(
        "calendar",
        "calendar_busy",
        "calendar_copies",
        "calendar_twins",
        "task_blocks",
        "travel",
    ),
)
