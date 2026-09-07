"""New standalone strategy classes for the overnight search. These live
ONLY here -- never imported by src/, never registered in
STRATEGY_REGISTRY. They reuse real production helpers read-only
(needs_maintenance, maintenance_action_for, opportunistic_* from mcts.py)
instead of reimplementing due/proximity classification, per this
codebase's established convention."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from src.models import ACTION_MOVE  # noqa: E402
from railroad_backend.services.auto_planner_strategies.base import AutoPlanStrategy, StepDecision  # noqa: E402
from railroad_backend.services.auto_planner_strategies.greedy import (  # noqa: E402
    days_until_next_threshold,
    maintenance_action_for,
    needs_maintenance,
    segments_already_due,
)
from railroad_backend.services.auto_planner_strategies.mcts import (  # noqa: E402
    opportunistic_maintenance_action_for,
    opportunistic_needs_maintenance,
)


class CorridorSweepStrategy(AutoPlanStrategy):
    """Structural heuristic mirroring the human's observed behavior
    (Task 5 field diagnostic, 2026-09-05: a clean corridor sweep out, then
    back, maintaining opportunistically along the way) more directly than
    Greedy/MCTS's urgency-ranked move selection: keep moving in whichever
    direction continues away from the station just visited (don't jump
    back and forth chasing the single highest-load segment), maintaining
    anything due or near-threshold along the way; only reverse when no
    forward option remains."""

    def __init__(self, *, proximity_ratio: float = 0.7) -> None:
        self.proximity_ratio = proximity_ratio
        self._last_station: Optional[str] = None

    def decide_next_action(self, sim) -> StepDecision:
        options = sim.get_possible_moves() or sim.get_all_moves_any_direction()
        if not options:
            if sim.current_station and sim.current_station.can_turn:
                return StepDecision(kind="turn")
            return StepDecision(kind="none")
        forward = [opt for opt in options if opt[1].name != self._last_station]
        segments, next_station = (forward or options)[0]
        self._last_station = sim.current_station.name if sim.current_station else None
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        elif opportunistic_needs_maintenance(segments, self.proximity_ratio):
            action = opportunistic_maintenance_action_for(segments, self.proximity_ratio)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


class MaximalOpportunisticStrategy(AutoPlanStrategy):
    """Same move-selection as Greedy (urgency-ranked), but maintains
    EVERY segment crossed regardless of load (proximity_ratio=0 in effect)
    -- tests whether "always maintain whatever you pass" beats a
    threshold-gated version, at the obvious cost of possibly wasting
    maintenance time on freshly-serviced segments."""

    def decide_next_action(self, sim) -> StepDecision:
        if segments_already_due(sim):
            options = sim.get_possible_moves()
            if not options:
                if sim.current_station and sim.current_station.can_turn:
                    return StepDecision(kind="turn")
                options = sim.get_all_moves_any_direction()
                if not options:
                    return StepDecision(kind="none")
            from railroad_backend.services.auto_planner_strategies.greedy import _move_priority

            segments, next_station = sorted(options, key=_move_priority)[0]
            action = maintenance_action_for(segments) if needs_maintenance(segments) else "maintain_curves"
            return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)
        wait_days = days_until_next_threshold(sim)
        if wait_days <= 0:
            if sim.daily_map:
                wait_days = 1
            else:
                return StepDecision(kind="none")
        return StepDecision(kind="wait", wait_days=wait_days)


__all__ = ["CorridorSweepStrategy", "MaximalOpportunisticStrategy"]
