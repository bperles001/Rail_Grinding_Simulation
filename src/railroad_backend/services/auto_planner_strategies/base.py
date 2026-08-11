"""Strategy interface separating Auto Planner decision-making from execution."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from src.models import Segment, Station
    from ...domain.simulator import Simulator


@dataclass(frozen=True)
class StepDecision:
    """One decision for a single Auto Planner step.

    `kind` is one of:
      - "move": travel across `segments` to `next_station`, performing
        `action` (may be `ACTION_MOVE` for a plain move with no maintenance).
      - "wait": stay in place for `wait_days` days.
      - "turn": flip global direction at the current (turn-capable) station.
      - "none": no valid action exists; the planner should stop.
    """

    kind: str
    segments: Optional[Tuple["Segment", ...]] = None
    next_station: Optional["Station"] = None
    action: Optional[str] = None
    wait_days: Optional[int] = None


class AutoPlanStrategy(abc.ABC):
    """Decides the next action for an Auto Planner run, given simulator state."""

    @abc.abstractmethod
    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        """Return the next decision for the current simulator state."""
        raise NotImplementedError


__all__ = ["StepDecision", "AutoPlanStrategy"]
