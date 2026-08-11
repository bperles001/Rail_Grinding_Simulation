"""Shared "solve once, commit until invalidated" execution layer.

Rolling-horizon strategies that resolve a full planning model on every
single real step suffer from "nervousness" -- a documented phenomenon in
rolling-horizon/MRP scheduling (Jensen 1993, "Nervousness and Reorder
Policies in Rolling Horizon Environments"; Heisig 2002, "Nervousness in
Material Requirements Planning Systems"; Kimms 1997, "Rolling Planning
Horizon") where near-tied solutions flip between consecutive replans,
causing the machine to oscillate between two targets instead of ever
committing to either. Confirmed on the real network: `RollingHorizonILPStrategy`
looped between two adjacent stations for dozens of steps after servicing
both, because every step re-solved from scratch with no memory of the
previous plan (2026-08-11 diagnostic).

This base class caches the resolved `WindowPlan` and keeps executing it
until either the plan is exhausted, or a candidate that's due *right now*
turns up outside the set the cached plan was built from.
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, List, Optional, Set

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import DueCandidate, project_due_candidates
from .rolling_ilp import WindowPlan
from .travel_graph import build_travel_graph, shortest_travel_days

if TYPE_CHECKING:
    import networkx as nx

    from ...domain.simulator import Simulator


class CommittedWindowStrategy(AutoPlanStrategy, abc.ABC):
    """Plans a window once, then executes the cached plan step by step
    instead of replanning from scratch on every real step."""

    def __init__(self, *, window_days: int = 60) -> None:
        self.window_days = window_days
        self._fallback = GreedyUrgencyStrategy()
        self._cached_plan: Optional[WindowPlan] = None
        self._cached_candidate_names: Set[str] = set()

    @abc.abstractmethod
    def _solve_window(
        self, candidates: List[DueCandidate], graph: "nx.DiGraph", start_station: str
    ) -> WindowPlan:
        """Solve one planning window. Implemented per concrete strategy."""
        raise NotImplementedError

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        station = sim.current_station
        if station is None:
            return self._fallback.decide_next_action(sim)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments)

        if self._should_replan(candidates):
            plan = self._solve_window(candidates, graph, station.name)
            self._cached_plan = plan
            self._cached_candidate_names = {c.segment_name for c in candidates}

        plan = self._cached_plan
        if plan is None or not plan.feasible or not plan.stops:
            self._cached_plan = None
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        target_segment_name = plan.stops[0].segment_name
        decision = self._next_real_move_toward(sim, graph, target_station)
        if decision.kind == "move" and any(seg.name == target_segment_name for seg in (decision.segments or ())):
            plan.stops.pop(0)
        return decision

    def _should_replan(self, candidates: List[DueCandidate]) -> bool:
        if self._cached_plan is None or not self._cached_plan.stops:
            return True
        newly_due = {c.segment_name for c in candidates if c.days_until_due == 0}
        return not newly_due.issubset(self._cached_candidate_names)

    def _next_real_move_toward(self, sim: "Simulator", graph, target_station: str) -> StepDecision:
        options = sim.get_possible_moves()
        if not options:
            # The current facing has no valid forward move -- try a turn
            # first (mirrors GreedyUrgencyStrategy's own dead-end handling),
            # then fall back to considering every physically adjacent
            # segment regardless of facing. Giving up on the cached target
            # here (falling straight to Greedy's unrelated local-priority
            # logic) is what caused the machine to abandon a still-valid,
            # still-modeled plan and oscillate between two nearby stations
            # for dozens of steps on the real network (2026-08-11 diagnostic).
            if sim.current_station and sim.current_station.can_turn:
                return StepDecision(kind="turn")
            options = sim.get_all_moves_any_direction()
        if not options:
            return self._fallback.decide_next_action(sim)

        def remaining_distance(option) -> float:
            segments, next_station = option
            distance = shortest_travel_days(graph, next_station.name, target_station)
            return float("inf") if distance is None else distance

        segments, next_station = min(options, key=remaining_distance)
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["CommittedWindowStrategy"]
