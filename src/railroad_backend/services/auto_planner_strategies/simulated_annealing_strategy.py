"""Simulated Annealing rolling-horizon strategy, built on the same
commitment base as the CP-SAT strategy."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from .committed_window import CommittedWindowStrategy
from .horizon import DueCandidate
from .rolling_ilp import WindowPlan
from .simulated_annealing import solve_window_sa

if TYPE_CHECKING:
    import networkx as nx


class SimulatedAnnealingStrategy(CommittedWindowStrategy):
    """Plans a rolling window with Simulated Annealing; commits to the
    resulting plan (via CommittedWindowStrategy) instead of replanning
    every real step."""

    def __init__(
        self,
        *,
        window_days: int = 90,
        weight_coverage: float = 10.0,
        weight_travel: float = 1.0,
        weight_proximity: float = 0.5,
        iterations: int = 2000,
        initial_temperature: float = 100.0,
        cooling_rate: float = 0.995,
        seed: Optional[int] = None,
    ) -> None:
        super().__init__(window_days=window_days)
        self.weight_coverage = weight_coverage
        self.weight_travel = weight_travel
        self.weight_proximity = weight_proximity
        self.iterations = iterations
        self.initial_temperature = initial_temperature
        self.cooling_rate = cooling_rate
        self.seed = seed

    def _solve_window(
        self, candidates: List[DueCandidate], graph: "nx.DiGraph", start_station: str
    ) -> WindowPlan:
        return solve_window_sa(
            candidates,
            graph,
            start_station=start_station,
            weight_coverage=self.weight_coverage,
            weight_travel=self.weight_travel,
            weight_proximity=self.weight_proximity,
            iterations=self.iterations,
            initial_temperature=self.initial_temperature,
            cooling_rate=self.cooling_rate,
            seed=self.seed,
        )


__all__ = ["SimulatedAnnealingStrategy"]
