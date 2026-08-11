"""Rolling-horizon CP-SAT strategy, with commitment (Task 1) to avoid
replanning from scratch every step, and a Greedy fallback for infeasible
windows."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from .committed_window import CommittedWindowStrategy
from .horizon import DueCandidate
from .rolling_ilp import WindowPlan, solve_window

if TYPE_CHECKING:
    import networkx as nx


class RollingHorizonILPStrategy(CommittedWindowStrategy):
    """Plans a rolling window with CP-SAT; commits to the resulting plan
    (via CommittedWindowStrategy) instead of replanning every real step."""

    def __init__(
        self,
        *,
        window_days: int = 60,
        weight_coverage: float = 10.0,
        weight_travel: float = 1.0,
        weight_proximity: float = 0.5,
        time_limit_s: float = 20.0,
    ) -> None:
        super().__init__(window_days=window_days)
        self.weight_coverage = weight_coverage
        self.weight_travel = weight_travel
        self.weight_proximity = weight_proximity
        self.time_limit_s = time_limit_s

    def _solve_window(
        self, candidates: List[DueCandidate], graph: "nx.DiGraph", start_station: str
    ) -> WindowPlan:
        return solve_window(
            candidates,
            graph,
            start_station=start_station,
            weight_coverage=self.weight_coverage,
            weight_travel=self.weight_travel,
            weight_proximity=self.weight_proximity,
            time_limit_s=self.time_limit_s,
        )


__all__ = ["RollingHorizonILPStrategy"]
