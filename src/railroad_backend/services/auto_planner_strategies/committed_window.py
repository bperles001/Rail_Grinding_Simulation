"""Shared "solve once, commit until invalidated" execution layer.

Rolling-horizon strategies that resolve a full planning model on every
single real step suffer from "nervousness" -- a documented phenomenon in
rolling-horizon/MRP scheduling (Jensen 1993, "Nervousness and Reorder
Policies in Rolling Horizon Environments"; Heisig 2002, "Nervousness in
Material Requirements Planning Systems"; Kimms 1997, "Rolling Planning
Horizon") where near-tied solutions flip between consecutive replans.

This base class caches the resolved `WindowPlan` and keeps executing it
until either the plan is exhausted, or a candidate that's due *right now*
turns up outside the set the cached plan was built from, or the cached
target becomes unreachable from wherever the machine actually is.

Real execution follows the exact shortest path (turn-aware, via
`shortest_path_first_step`) instead of picking whichever immediately
adjacent option looks closest -- the greedy nearest-neighbor heuristic
could wander into a pocket the target wasn't reachable from without an
un-modeled turn, and then had no signal left to prefer forward progress
over backtracking (confirmed on the real network as an indefinite
2-station oscillation -- 2026-08-11/12 diagnostic).
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, List, Optional, Set

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import DueCandidate, project_due_candidates
from .rolling_ilp import WindowPlan
from .travel_graph import State, build_travel_graph, shortest_path_first_step, shortest_travel_days

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
        if station is None or sim.machine is None:
            return self._fallback.decide_next_action(sim)
        current_state: State = (station.name, sim.machine.global_direction)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments, sim.stations)

        if self._should_replan(candidates, graph, current_state):
            plan = self._solve_window(candidates, graph, station.name)
            self._cached_plan = plan
            self._cached_candidate_names = {c.segment_name for c in candidates}

        plan = self._cached_plan
        if plan is None or not plan.feasible or not plan.stops:
            self._cached_plan = None
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        target_segment_name = plan.stops[0].segment_name
        decision = self._next_real_move_toward(sim, graph, current_state, target_station)
        if decision.kind == "move" and any(seg.name == target_segment_name for seg in (decision.segments or ())):
            plan.stops.pop(0)
        return decision

    def _should_replan(self, candidates: List[DueCandidate], graph: "nx.DiGraph", current_state: State) -> bool:
        if self._cached_plan is None or not self._cached_plan.stops:
            return True
        newly_due = {c.segment_name for c in candidates if c.days_until_due == 0}
        if not newly_due.issubset(self._cached_candidate_names):
            return True
        target_station = self._cached_plan.stops[0].station_name
        if shortest_travel_days(graph, current_state, target_station) is None:
            return True
        return False

    def _next_real_move_toward(
        self, sim: "Simulator", graph: "nx.DiGraph", current_state: State, target_station: str
    ) -> StepDecision:
        step = shortest_path_first_step(graph, current_state, target_station)
        if step is None:
            return self._fallback.decide_next_action(sim)
        if step.kind == "turn":
            return StepDecision(kind="turn")

        options = sim.get_possible_moves() or sim.get_all_moves_any_direction()
        match = next((opt for opt in options if opt[1].name == step.next_station), None)
        if match is None:
            return self._fallback.decide_next_action(sim)
        segments, next_station = match
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["CommittedWindowStrategy"]
