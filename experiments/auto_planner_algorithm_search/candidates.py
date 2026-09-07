"""Candidate strategy definitions for the overnight search. Appended to
incrementally across batches -- each batch adds a new CANDIDATES_BATCH_N
list; run_batch.py takes a batch name on the command line.

MCTS candidates only ever use MCTSStrategy's already-exposed constructor
kwargs (time_budget_s, exploration_constant, rollout_max_days,
proximity_ratio) -- zero risk of touching production state. New
structural heuristics live in strategies.py, never in src/.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from railroad_backend.services.auto_planner_strategies.greedy import GreedyUrgencyStrategy  # noqa: E402
from railroad_backend.services.auto_planner_strategies.mcts_strategy import MCTSStrategy  # noqa: E402

from strategies import CorridorSweepStrategy, MaximalOpportunisticStrategy  # noqa: E402

Candidate = Dict[str, Any]


def _mcts_grid() -> List[Candidate]:
    """27-point grid over rollout depth x proximity ratio x exploration
    constant, at a fixed cheap time_budget_s=2.0 for search speed
    (production default is 10.0 -- only the eventual finalist gets
    validated at a realistic budget via run_full)."""
    candidates: List[Candidate] = []
    for rollout_max_days, proximity_ratio, exploration_constant in itertools.product(
        (20, 45, 90), (0.5, 0.7, 0.85), (0.7, 1.41, 2.5)
    ):
        cid = f"mcts_grid_rd{rollout_max_days}_pr{proximity_ratio}_ec{exploration_constant}"
        params = dict(
            time_budget_s=2.0,
            rollout_max_days=rollout_max_days,
            proximity_ratio=proximity_ratio,
            exploration_constant=exploration_constant,
        )

        def make_strategy(_params=params) -> MCTSStrategy:
            return MCTSStrategy(**_params)

        candidates.append({"id": cid, "category": "mcts_hyperparam_grid", "params": params, "make_strategy": make_strategy})
    return candidates


def _heuristics() -> List[Candidate]:
    return [
        {
            "id": "heuristic_corridor_sweep_pr0.7",
            "category": "structural_heuristic",
            "params": {"proximity_ratio": 0.7},
            "make_strategy": lambda: CorridorSweepStrategy(proximity_ratio=0.7),
        },
        {
            "id": "heuristic_corridor_sweep_pr0.5",
            "category": "structural_heuristic",
            "params": {"proximity_ratio": 0.5},
            "make_strategy": lambda: CorridorSweepStrategy(proximity_ratio=0.5),
        },
        {
            "id": "heuristic_maximal_opportunistic",
            "category": "structural_heuristic",
            "params": {},
            "make_strategy": lambda: MaximalOpportunisticStrategy(),
        },
        {
            "id": "baseline_greedy",
            "category": "baseline",
            "params": {},
            "make_strategy": lambda: GreedyUrgencyStrategy(),
        },
    ]


BATCH_1: List[Candidate] = _mcts_grid() + _heuristics()

BATCHES: Dict[str, List[Candidate]] = {
    "batch1": BATCH_1,
}
