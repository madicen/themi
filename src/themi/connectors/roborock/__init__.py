"""Roborock: the robot vacuum, through the unofficial `python-roborock` library (V1)."""

from themi.connectors.roborock.client import (
    BadCode,
    LoginExpired,
    RoborockAccount,
    RoborockError,
    RoborockLogin,
    RoborockSession,
    RobotOffline,
    VacuumDevice,
)
from themi.connectors.roborock.events import (
    BIN,
    FAULT,
    JAMMED,
    NOT_DOCKED,
    PART,
    STUCK,
    WATER_EMPTY,
    WATER_FULL,
    VacuumEvent,
    VacuumStatus,
)
from themi.connectors.roborock.watch import PROVIDER, RoborockWatcher, VacuumListener

__all__ = [
    "BIN",
    "FAULT",
    "JAMMED",
    "NOT_DOCKED",
    "PART",
    "PROVIDER",
    "STUCK",
    "WATER_EMPTY",
    "WATER_FULL",
    "BadCode",
    "LoginExpired",
    "RoborockAccount",
    "RoborockError",
    "RoborockLogin",
    "RoborockSession",
    "RoborockWatcher",
    "RobotOffline",
    "VacuumDevice",
    "VacuumEvent",
    "VacuumListener",
    "VacuumStatus",
]
