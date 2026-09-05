"""MCTS Auto Planner strategy: decides one real move at a time via Monte
Carlo Tree Search with an opportunistic-maintenance-biased rollout policy,
reusing the relevant search subtree across consecutive real decisions."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from .base import AutoPlanStrategy, StepDecision
from .mcts import PROXIMITY_RATIO, ROLLOUT_MAX_DAYS, MCTSNode, search

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


class MCTSStrategy(AutoPlanStrategy):
    """Every real decision runs a fresh MCTS search (UCB1 selection,
    expansion, opportunistic-biased rollout, backpropagation) within a
    time budget, reusing the previous call's chosen subtree as a warm
    start -- game-engine style tree reuse, since the real world always
    executes exactly what this strategy last chose."""

    def __init__(
        self,
        *,
        time_budget_s: float = 10.0,
        exploration_constant: float = math.sqrt(2),
        rollout_max_days: int = ROLLOUT_MAX_DAYS,
        proximity_ratio: float = PROXIMITY_RATIO,
    ) -> None:
        self.time_budget_s = time_budget_s
        self.exploration_constant = exploration_constant
        self.rollout_max_days = rollout_max_days
        self.proximity_ratio = proximity_ratio
        self._root: Optional[MCTSNode] = None

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        decision, new_root = search(
            sim,
            self._root,
            time_budget_s=self.time_budget_s,
            exploration_constant=self.exploration_constant,
            rollout_max_days=self.rollout_max_days,
            proximity_ratio=self.proximity_ratio,
        )
        self._root = new_root
        return decision


__all__ = ["MCTSStrategy"]
