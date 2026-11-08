"""Cozyla: the family's wall calendar, through its unofficial cloud API (C1, C2)."""

from themi_cozyla.connector.chores import (
    Chore,
    ChoreRecord,
    Routine,
    RoutineRecord,
    WallSchedule,
)
from themi_cozyla.connector.client import (
    CozylaClient,
    CozylaConfig,
    CozylaError,
    CozylaMember,
    Todo,
    TodoList,
)

# CR21b: where the wall's ticks were made, for "Ticked off on the wall: ..."
WALL_WHERE = "on the wall"

__all__ = [
    "WALL_WHERE",
    "Chore",
    "ChoreRecord",
    "CozylaClient",
    "CozylaConfig",
    "CozylaError",
    "CozylaMember",
    "Routine",
    "RoutineRecord",
    "Todo",
    "TodoList",
    "WallSchedule",
]
