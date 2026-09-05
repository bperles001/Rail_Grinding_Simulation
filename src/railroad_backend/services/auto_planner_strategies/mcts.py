"""Monte Carlo Tree Search Auto Planner strategy with opportunistic
maintenance grouping.

Real planning-time benchmark on the real network (57 segments,
network_20251223_115340.json): naive `copy.deepcopy(sim)` costs ~43ms/clone
(~23/s) -- far too slow for MCTS, which needs hundreds to thousands of
simulated clones per real decision. Sharing `daily_map` by reference (it
never changes during simulation, only read) via deepcopy's `memo`
parameter cuts that to ~2.4ms/clone (~426/s). A full clone + 15-simulated-
day rollout measured ~5.1ms (~197 rollouts/sec) -- around 1970 rollouts
fit in a 10-second budget.
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


def clone_simulator(sim: "Simulator") -> "Simulator":
    """Cheap clone for MCTS rollouts: deep-copies all mutable simulation
    state (segment loads, machine position/direction, simulation date,
    counters) but shares the read-only daily traffic map by reference --
    deep-copying it repeatedly for every rollout clone was the dominant
    cost in benchmarking (see module docstring)."""
    memo = {}
    if sim.daily_map is not None:
        memo[id(sim.daily_map)] = sim.daily_map
    return copy.deepcopy(sim, memo)


__all__ = ["clone_simulator"]
