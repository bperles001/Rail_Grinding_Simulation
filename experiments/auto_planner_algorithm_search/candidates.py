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


def _batch2() -> List[Candidate]:
    """Informed by batch1: the standout region was rollout_max_days=45,
    proximity_ratio=0.85 (14 segments over threshold at the 180-day
    horizon, vs. 21-92 for everything else tried) -- exploration_constant
    made zero difference anywhere in batch1's grid, so it's fixed at
    sqrt(2) here. rollout_max_days=90 catastrophically collapsed (64
    segments over, worse than baseline) at every proximity_ratio, most
    likely because longer rollouts leave far fewer total simulations
    inside the same 2s search budget -- not chased further here, just
    avoided in this refined grid.

    This batch: (a) a finer proximity_ratio x rollout_max_days grid
    around the winning region, (b) a proximity_ratio=1.0 control (pure
    "only maintain when truly due", isolating whether the opportunistic
    bias itself is even helping at this budget), (c) a time_budget_s
    robustness check on the current best config, (d) a longer (365-day)
    horizon robustness check on the current best config, since the
    180-day result could in principle be a lucky early-window artifact.
    """
    candidates: List[Candidate] = []

    for rollout_max_days, proximity_ratio in itertools.product((30, 45, 60), (0.8, 0.85, 0.9, 0.95)):
        cid = f"mcts_refine_rd{rollout_max_days}_pr{proximity_ratio}"
        params = dict(time_budget_s=2.0, rollout_max_days=rollout_max_days, proximity_ratio=proximity_ratio, exploration_constant=1.41)

        def make_strategy(_params=params) -> MCTSStrategy:
            return MCTSStrategy(**_params)

        candidates.append({"id": cid, "category": "mcts_refined_grid", "params": params, "make_strategy": make_strategy})

    # Control: proximity_ratio=1.0 == only maintain when strictly due (no
    # opportunistic bias at all), same rollout depth as the batch1 winner.
    control_params = dict(time_budget_s=2.0, rollout_max_days=45, proximity_ratio=1.0, exploration_constant=1.41)
    candidates.append(
        {
            "id": "mcts_control_no_opportunism_rd45_pr1.0",
            "category": "mcts_control",
            "params": control_params,
            "make_strategy": lambda _p=control_params: MCTSStrategy(**_p),
        }
    )

    # Time-budget robustness on the batch1 winner.
    for time_budget_s in (1.0, 5.0, 10.0):
        params = dict(time_budget_s=time_budget_s, rollout_max_days=45, proximity_ratio=0.85, exploration_constant=1.41)
        candidates.append(
            {
                "id": f"mcts_budget_robustness_tb{time_budget_s}",
                "category": "mcts_budget_robustness",
                "params": params,
                "make_strategy": lambda _p=params: MCTSStrategy(**_p),
            }
        )

    # Longer-horizon robustness check on the batch1 winner (365 days
    # instead of 180) -- more steps needed, so a generous max_steps.
    winner_params = dict(time_budget_s=2.0, rollout_max_days=45, proximity_ratio=0.85, exploration_constant=1.41)
    candidates.append(
        {
            "id": "mcts_winner_horizon365",
            "category": "mcts_horizon_robustness",
            "params": winner_params,
            "make_strategy": lambda _p=winner_params: MCTSStrategy(**_p),
            "max_days": 365,
            "max_steps": 500,
        }
    )
    return candidates


BATCH_2: List[Candidate] = _batch2()

BATCHES: Dict[str, List[Candidate]] = {
    "batch1": BATCH_1,
    "batch2": BATCH_2,
}
