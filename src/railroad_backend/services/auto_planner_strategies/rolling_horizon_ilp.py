"""Rolling-horizon CP-SAT strategy with a Greedy fallback for infeasible windows."""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import project_due_candidates
from .rolling_ilp import solve_window
from .travel_graph import build_travel_graph, shortest_travel_days

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


class RollingHorizonILPStrategy(AutoPlanStrategy):
    """Plans a rolling window with CP-SAT; executes only the first action of
    the best plan found, and replans from scratch on the next call."""

    def __init__(
        self,
        *,
        window_days: int = 60,
        weight_coverage: float = 10.0,
        weight_travel: float = 1.0,
        weight_proximity: float = 0.5,
        time_limit_s: float = 20.0,
    ) -> None:
        self.window_days = window_days
        self.weight_coverage = weight_coverage
        self.weight_travel = weight_travel
        self.weight_proximity = weight_proximity
        self.time_limit_s = time_limit_s
        self._fallback = GreedyUrgencyStrategy()

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        station = sim.current_station
        if station is None:
            return self._fallback.decide_next_action(sim)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments)
        plan = solve_window(
            candidates,
            graph,
            start_station=station.name,
            weight_coverage=self.weight_coverage,
            weight_travel=self.weight_travel,
            weight_proximity=self.weight_proximity,
            time_limit_s=self.time_limit_s,
        )

        if not plan.feasible or not plan.stops:
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        return self._next_real_move_toward(sim, graph, target_station)

    def _next_real_move_toward(self, sim: "Simulator", graph, target_station: str) -> StepDecision:
        options = sim.get_possible_moves()
        if not options:
            return self._fallback.decide_next_action(sim)

        def remaining_distance(option) -> float:
            segments, next_station = option
            distance = shortest_travel_days(graph, next_station.name, target_station)
            return float("inf") if distance is None else distance

        segments, next_station = min(options, key=remaining_distance)
        # Maintain whenever the segments about to be crossed are due, full
        # stop -- not only when this happens to be the modeled window's
        # first-choice target. The model re-solves every step and its
        # "first stop" can point further down the corridor than the very
        # next physical hop; refusing a free, already-due maintenance along
        # the way just to stay "on plan" left segments loaded at ~8x their
        # threshold un-serviced while the machine drove straight through
        # them (2026-08-11 diagnostic).
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["RollingHorizonILPStrategy"]
