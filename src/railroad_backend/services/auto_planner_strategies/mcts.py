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


from typing import Tuple

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE

from .base import StepDecision
from .greedy import (
    _move_priority,
    days_until_next_threshold,
    needs_maintenance,
    segments_already_due,
)

# NOTE: _execute_decision is imported lazily (inside run_rollout/search, not
# here at module level) -- Task 4 registers MCTSStrategy in auto_planner.py's
# STRATEGY_REGISTRY dict, which is defined *before* _execute_decision in that
# file; a module-level `from ..auto_planner import _execute_decision` here
# would make auto_planner.py's own import of mcts_strategy.py (which imports
# this module) circular back into itself before _execute_decision exists,
# raising ImportError. Deferring the import until call time sidesteps it
# entirely, since by then the whole module graph is fully loaded.

PROXIMITY_RATIO = 0.7
ROLLOUT_MAX_DAYS = 45
OPPORTUNISTIC_BONUS_WEIGHT = 5.0
WEIGHT_COVERAGE = 10.0
WEIGHT_TRAVEL = 1.0


def _component_near_threshold(seg, component: str, ratio: float) -> bool:
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    if not threshold:
        return False
    load = float(getattr(seg, f"load_{component}", 0.0) or 0.0)
    return load >= ratio * float(threshold)


def opportunistic_needs_maintenance(segments, ratio: float = PROXIMITY_RATIO) -> bool:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    return any(
        _component_near_threshold(seg, "curva", ratio) or _component_near_threshold(seg, "tangente", ratio)
        for seg in seq
    )


def opportunistic_maintenance_action_for(segments, ratio: float = PROXIMITY_RATIO) -> str:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    if any(_component_near_threshold(seg, "tangente", ratio) for seg in seq):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES


def opportunistic_rollout_decision(sim: "Simulator", *, proximity_ratio: float = PROXIMITY_RATIO) -> StepDecision:
    """Same move-selection logic as GreedyUrgencyStrategy (move toward the
    most urgent already-due segment, by _move_priority), but the
    maintenance decision uses a proximity threshold instead of strict due
    status. Because move *selection* here is still driven purely by strict
    due-priority (this function never routes toward a near-threshold
    segment on its own), every opportunistic maintenance this produces
    happens during a move that was already going to happen for another
    reason -- there is no code path where the sole purpose of a move is an
    opportunistic (not-yet-due) segment, so no separate "was this move
    already happening anyway" bookkeeping is needed."""
    if segments_already_due(sim):
        options = sim.get_possible_moves()
        if not options:
            if sim.current_station and sim.current_station.can_turn:
                return StepDecision(kind="turn")
            options = sim.get_all_moves_any_direction()
            if not options:
                return StepDecision(kind="none")
        segments, next_station = sorted(options, key=_move_priority)[0]
        if opportunistic_needs_maintenance(segments, proximity_ratio):
            action = opportunistic_maintenance_action_for(segments, proximity_ratio)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)

    wait_days = days_until_next_threshold(sim)
    if wait_days <= 0:
        if sim.daily_map:
            wait_days = 1
        else:
            return StepDecision(kind="none")
    return StepDecision(kind="wait", wait_days=wait_days)


def run_rollout(
    sim: "Simulator", *, max_days: int = ROLLOUT_MAX_DAYS, proximity_ratio: float = PROXIMITY_RATIO
) -> Tuple["Simulator", int]:
    """Simulates forward from `sim` (must already be a clone -- this
    mutates it in place) for up to `max_days` of simulated calendar time
    using the opportunistic rollout policy. Returns the mutated simulator
    and a count of segments maintained opportunistically (near threshold
    but not strictly due at the moment the maintenance decision was made)."""
    from ..auto_planner import _execute_decision  # local import -- see note above

    start_date = sim.simulation_date
    opportunistic_count = 0
    while True:
        if sim.simulation_date and start_date and (sim.simulation_date - start_date).days >= max_days:
            break
        decision = opportunistic_rollout_decision(sim, proximity_ratio=proximity_ratio)
        if decision.kind == "move" and decision.action != ACTION_MOVE and not needs_maintenance(decision.segments):
            opportunistic_count += 1
        if not _execute_decision(sim, decision):
            break
    return sim, opportunistic_count


def evaluate_rollout_outcome(
    before: "Simulator",
    after: "Simulator",
    opportunistic_count: int,
    *,
    weight_coverage: float = WEIGHT_COVERAGE,
    weight_travel: float = WEIGHT_TRAVEL,
    weight_opportunistic_bonus: float = OPPORTUNISTIC_BONUS_WEIGHT,
) -> float:
    """Higher is better. Coverage penalty is severity-weighted (a segment
    loaded at 3x its threshold costs 3x as much as one that just crossed
    it) -- same severity concept already used by the ILP/SA strategies
    (DueCandidate.severity in horizon.py)."""
    severity_penalty = 0.0
    for seg in after.segments:
        if seg.mtbt_threshold_curva and seg.load_curva >= seg.mtbt_threshold_curva:
            severity_penalty += seg.load_curva / seg.mtbt_threshold_curva
        if seg.mtbt_threshold_tangente and seg.load_tangente >= seg.mtbt_threshold_tangente:
            severity_penalty += seg.load_tangente / seg.mtbt_threshold_tangente
    travel_days = after.movement_days_total - before.movement_days_total
    cost = weight_coverage * severity_penalty + weight_travel * travel_days
    bonus = weight_opportunistic_bonus * opportunistic_count
    return bonus - cost


import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .greedy import maintenance_action_for

DecisionKey = tuple


def decision_key(decision: StepDecision) -> DecisionKey:
    if decision.kind == "move":
        return ("move", tuple(seg.name for seg in decision.segments), decision.next_station.name, decision.action)
    if decision.kind == "wait":
        return ("wait", decision.wait_days)
    if decision.kind == "turn":
        return ("turn",)
    return ("none",)


def resolve_decision(sim: "Simulator", key: DecisionKey) -> StepDecision:
    """Reconstructs a real, executable StepDecision against `sim`'s own
    Segment/Station objects. Never reuse a StepDecision's object
    references across a different simulator instance -- see the
    object-identity gotcha in the plan's Global Constraints."""
    kind = key[0]
    if kind == "move":
        _, seg_names, next_station_name, action = key
        by_name = {seg.name: seg for seg in sim.segments}
        segments = tuple(by_name[name] for name in seg_names)
        next_station = sim.stations[next_station_name]
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)
    if kind == "wait":
        return StepDecision(kind="wait", wait_days=key[1])
    if kind == "turn":
        return StepDecision(kind="turn")
    return StepDecision(kind="none")


def enumerate_decision_keys(sim: "Simulator") -> List[DecisionKey]:
    """Every real decision reachable from `sim`'s current state, one per
    move (plus turn/wait). The maintenance action on a move uses the same
    proximity rule as the rollout policy (due first, else opportunistic,
    else plain move) -- per spec, real execution (the root child MCTS
    finally returns) must be consistent with what the tree actually
    searched, not a stricter binary check applied only at the end."""
    keys: List[DecisionKey] = []
    moves = sim.get_possible_moves() or sim.get_all_moves_any_direction()
    for segments, next_station in moves:
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        elif opportunistic_needs_maintenance(segments):
            action = opportunistic_maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        keys.append(("move", tuple(seg.name for seg in segments), next_station.name, action))
    if sim.current_station and sim.current_station.can_turn:
        keys.append(("turn",))
    if not keys:
        wait_days = days_until_next_threshold(sim)
        if wait_days > 0:
            keys.append(("wait", wait_days))
    return keys


@dataclass
class MCTSNode:
    decision_key: Optional[DecisionKey]
    parent: Optional["MCTSNode"]
    children: Dict[DecisionKey, "MCTSNode"] = field(default_factory=dict)
    visits: int = 0
    total_value: float = 0.0
    untried_keys: Optional[List[DecisionKey]] = None

    @property
    def mean_value(self) -> float:
        return self.total_value / self.visits if self.visits else 0.0

    def ucb1(self, exploration_constant: float) -> float:
        if self.visits == 0:
            return math.inf
        parent_visits = self.parent.visits if self.parent else 1
        return self.mean_value + exploration_constant * math.sqrt(math.log(max(1, parent_visits)) / self.visits)


def search(
    root_sim: "Simulator",
    root: Optional[MCTSNode] = None,
    *,
    time_budget_s: Optional[float] = None,
    max_iterations: Optional[int] = None,
    exploration_constant: float = math.sqrt(2),
    rollout_max_days: int = ROLLOUT_MAX_DAYS,
    proximity_ratio: float = PROXIMITY_RATIO,
) -> Tuple[StepDecision, MCTSNode]:
    from ..auto_planner import _execute_decision  # local import -- see note in run_rollout

    if (time_budget_s is None) == (max_iterations is None):
        raise ValueError("search() requires exactly one of time_budget_s or max_iterations")
    if root is None:
        root = MCTSNode(decision_key=None, parent=None)

    deadline = time.monotonic() + time_budget_s if time_budget_s is not None else None
    iterations = 0
    while (deadline is None or time.monotonic() < deadline) and (max_iterations is None or iterations < max_iterations):
        iterations += 1
        node = root
        sim = clone_simulator(root_sim)

        # Selection: descend while every child has been tried at least once.
        while node.untried_keys is not None and not node.untried_keys and node.children:
            best_child = max(node.children.values(), key=lambda c: c.ucb1(exploration_constant))
            _execute_decision(sim, resolve_decision(sim, best_child.decision_key))
            node = best_child

        # Expansion.
        if node.untried_keys is None:
            node.untried_keys = enumerate_decision_keys(sim)
        if node.untried_keys:
            key = node.untried_keys.pop()
            _execute_decision(sim, resolve_decision(sim, key))
            child = MCTSNode(decision_key=key, parent=node)
            node.children[key] = child
            node = child

        # Rollout + backpropagation.
        rollout_sim, opportunistic_count = run_rollout(sim, max_days=rollout_max_days, proximity_ratio=proximity_ratio)
        value = evaluate_rollout_outcome(root_sim, rollout_sim, opportunistic_count)
        while node is not None:
            node.visits += 1
            node.total_value += value
            node = node.parent

    if not root.children:
        return StepDecision(kind="none"), root
    best = max(root.children.values(), key=lambda c: c.visits)
    best.parent = None
    return resolve_decision(root_sim, best.decision_key), best


__all__ = [
    "clone_simulator",
    "opportunistic_needs_maintenance",
    "opportunistic_maintenance_action_for",
    "opportunistic_rollout_decision",
    "run_rollout",
    "evaluate_rollout_outcome",
    "decision_key",
    "resolve_decision",
    "enumerate_decision_keys",
    "MCTSNode",
    "search",
]
