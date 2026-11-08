"""Who takes a task: the usual person, unless the other partner clearly has more room.

    cost(person)  = effort x 8 x their cost for this kind x recovery factor
    spare(person) = capacity now - cost(person)

The task goes to the default owner for its kind (family setting) unless the
partner's spare room, minus the cost of handing it over, still beats the
default owner's. The recovery factor makes draining work cost a little more
for someone who recovers slowly (half-life above 6 hours) and a little less
for a fast recoverer.

The reason is recorded in words; no numbers leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from themi import clock
from themi.accounts import AccountStore, Member
from themi.energy.model import SOURCE_INPUT, EnergyModel
from themi.localtime import to_local

POINTS_PER_EFFORT = 8.0
KIND_WORDS = {"text": "texting", "call": "calls", "physical": "hands-on jobs", "errand": "errands"}


@dataclass(frozen=True)
class Assignment:
    assignee: Member
    default_owner: Member
    reason: str

    @property
    def swapped(self) -> bool:
        return self.assignee.id != self.default_owner.id


def recovery_factor(recovery_hours: float) -> float:
    return max(0.75, min(1.5, 1 + (recovery_hours - 6) / 24))


def task_cost(member: Member, kind: str, effort: int) -> float:
    return (
        effort * POINTS_PER_EFFORT * member.kind_cost(kind) * recovery_factor(member.recovery_hours)
    )


def _tracked(member: Member) -> bool:
    return any(member.tracks(toggle) for toggle in SOURCE_INPUT.values())


TASK_LOAD_POINTS = 2.0  # per open task; an overdue one counts twice
TASK_LOAD_CAP = 15.0


def not_set_aside(set_aside: list[str], column: str = "id") -> str:
    """SQL that leaves out tasks a module has set aside (`set_aside`: subqueries of task
    ids), for "AND ..." in a query of open tasks. "1 = 1" when nothing is."""
    return " AND ".join(f"{column} NOT IN ({q})" for q in set_aside) or "1 = 1"


class Matcher:
    def __init__(self, store: AccountStore, model: EnergyModel) -> None:
        self.store = store
        self.model = model
        # Open tasks that someone isn't asked about while others stand in for them (a
        # split task while its parts are open, F26c): subqueries of task ids, which a
        # module adds. The task board shares this list.
        self.set_aside: list[str] = []

    def default_owner(self, kind: str, requester: Member) -> Member:
        family = self.store.get_family()
        owner_id = family.task_owners.get(kind) if family else None
        if owner_id is not None:
            try:
                return self.store.get_member(owner_id)
            except Exception:  # the owner was removed; fall back to the requester
                pass
        return requester

    def spare(self, member: Member, kind: str, effort: int, at: datetime | None = None) -> float:
        return (
            self.model.capacity(member, at)
            - task_cost(member, kind, effort)
            - self.task_load(member)
        )

    def task_load(self, member: Member) -> float:
        """What's already on their plate (S2): each open task a little, overdue ones double,
        capped, so matching doesn't pile more onto someone who's behind."""
        family = self.store.get_family()
        today = to_local(clock.now(), family.timezone if family else "UTC").date()
        row = self.store.db.one(
            "SELECT COUNT(*) AS open, SUM(CASE WHEN due_on < ? THEN 1 ELSE 0 END) AS overdue "
            "FROM tasks WHERE assignee = ? AND status IN ('open', 'snoozed') "
            f"AND {not_set_aside(self.set_aside)}",  # F26c: a split task's parts count
            (today.isoformat(), member.id),
        )
        if row is None:
            return 0.0
        return min(TASK_LOAD_CAP, TASK_LOAD_POINTS * (row["open"] + (row["overdue"] or 0)))

    def roomiest(self, kind: str, effort: int, at: datetime | None = None) -> Assignment:
        """For a job nobody owns (the washer's done, 31): whoever has the most spare room
        right now, with no hand-over cost. Without an energy read on anyone, an admin."""
        now = at or clock.now()
        members = self.store.list_members()
        tracked = [m for m in members if _tracked(m)]
        if not tracked:
            admin = next((m for m in members if m.is_admin), members[0])
            return Assignment(admin, admin, "No energy read to weigh it with.")
        best = max(tracked, key=lambda m: self.spare(m, kind, effort, now))  # ties: the first
        if len(members) == 1:
            return Assignment(best, best, f"{best.name}'s, the only one here.")
        return Assignment(best, best, f"{best.name} seems to have the most room right now.")

    def assign(
        self, kind: str, effort: int, requester: Member, at: datetime | None = None
    ) -> Assignment:
        now = at or clock.now()
        default = self.default_owner(kind, requester)
        others = [m for m in self.store.list_members() if m.id != default.id]
        usual = f"Usually {default.name}'s ({KIND_WORDS.get(kind, kind)})"
        if not others:
            return Assignment(default, default, f"{usual}.")
        if not _tracked(default):
            return Assignment(default, default, f"{usual}; no energy read to weigh it against.")
        family = self.store.get_family()
        handover = family.handover_cost if family else 10.0
        default_spare = self.spare(default, kind, effort, now)
        best, best_spare = None, default_spare + handover
        for other in others:
            if not _tracked(other):
                continue
            other_spare = self.spare(other, kind, effort, now)
            if other_spare > best_spare:
                best, best_spare = other, other_spare
        if best is None:
            return Assignment(default, default, f"{usual}.")
        return Assignment(
            best, default, f"{usual}, but {best.name} seems to have more room right now."
        )
