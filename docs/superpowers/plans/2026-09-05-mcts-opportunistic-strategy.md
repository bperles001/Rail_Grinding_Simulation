# MCTS Opportunistic Maintenance Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fourth Auto Planner strategy (`MCTSStrategy`) that decides one real move at a time by running Monte Carlo Tree Search — simulating many possible futures with a fast, opportunistically-biased rollout policy before choosing — closing the measured gap against real human-planned maintenance (81-93% of time on real maintenance vs. 65-71% for the three existing automated strategies).

**Architecture:** `MCTSStrategy` implements `AutoPlanStrategy` directly (not `CommittedWindowStrategy` — MCTS re-evaluates every real step by design, informed by a real search tree, unlike the naive memoryless replanning `CommittedWindowStrategy` was built to fix). Each real decision runs UCT-style MCTS (selection via UCB1, expansion, rollout via a cheap opportunistic-biased policy, backpropagation) against cloned `Simulator` instances, reusing the relevant search subtree across real steps. The rollout policy and reward function both carry an explicit opportunistic-maintenance bias: maintain segments crossed while already moving for another reason, once they're loaded above a proximity threshold, even before they're strictly "due."

**Tech Stack:** Python 3.10+, `copy.deepcopy` with a memo-based optimization (no new dependency), same test/repo conventions as the three existing strategies.

**Spec:** `docs/superpowers/specs/2026-09-05-mcts-opportunistic-strategy-design.md`

## Global Constraints

- Repo: `E:\Projetos\Simulador de Esmerilhamento\railroad-maintenance-simulator`. Work directly on `master`, commit after every task (this repo's established pattern — no feature branches).
- **No UI changes.** All MCTS parameters (time budget, UCB1 exploration constant, rollout depth, proximity threshold, opportunistic bonus weight) are constructor defaults / internal constants — never exposed through `AutoPlanConfig`'s public UI-facing fields beyond `strategy="mcts"` itself.
- Real numbers measured during planning (`network_20251223_115340.json`, 57 segments): naive `copy.deepcopy(sim)` costs ~43ms/clone (~23/s); sharing `daily_map` by reference via `deepcopy`'s `memo` parameter cuts that to ~2.4ms/clone (~426/s); a full clone + 15-simulated-day rollout (using `GreedyUrgencyStrategy` as a stand-in policy) costs ~5.1ms, i.e. ~197 rollouts/second — around **1970 rollouts fit in a 10-second budget**. Use the memo optimization; do not re-benchmark naive `deepcopy` as a viable path.
- Run `python -m pytest` (full suite) after every task — zero regressions is this repo's established bar.
- `.venv\Scripts\python.exe` is this repo's real interpreter.
- **Object-identity gotcha (read before Task 3):** each MCTS rollout clones the `Simulator` fresh via `copy.deepcopy`, which produces entirely new `Segment`/`Station` objects every time. A `StepDecision` holding references to one clone's `Segment`/`Station` objects is invalid if executed against a *different* clone (or the real `Simulator`) — `move_to()` mutates whatever objects it's handed directly, without checking they belong to the simulator's own `sim.segments`/`sim.stations`, so passing cross-clone objects silently corrupts state (the move "happens" on the wrong object graph, and the target simulator's own state doesn't reflect it). The tree must therefore store **decision signatures** (segment names, station name, action — plain data) and re-resolve them against whichever simulator instance is executing at the moment, never cache live `StepDecision` objects across clone boundaries.

---

## Task 1: `clone_simulator` — cheap simulator cloning for rollouts

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/mcts.py`
- Test: `tests/test_mcts.py`

**Interfaces:**
- Produces: `clone_simulator(sim: Simulator) -> Simulator`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcts.py
"""Tests for the MCTS Auto Planner strategy: cloning, opportunistic rollout
policy, tree search, and the public MCTSStrategy."""
import time
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.mcts import clone_simulator


def _config(tmp_path: Path) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_clone_simulator_produces_an_independent_copy(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    clone = clone_simulator(sim)
    assert clone is not sim
    clone_seg = next(s for s in clone.segments if s.name == "TRO-TMI")
    real_seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    assert clone_seg is not real_seg
    clone_seg.load_curva = 999.0
    assert real_seg.load_curva != 999.0


def test_clone_simulator_shares_the_daily_map_by_reference(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    clone = clone_simulator(sim)
    assert clone.daily_map is sim.daily_map


def test_clone_simulator_is_fast_enough_for_hundreds_of_rollouts_per_second(tmp_path):
    """Regression guard for the memo-based optimization this function
    depends on: a naive `copy.deepcopy(sim)` (no memo) measured ~23
    clones/second on the real 57-segment network during planning -- far
    too slow for MCTS (needs hundreds to thousands of simulations per
    real decision within a ~10s budget). The memo-optimized version
    measured ~426 clones/second on that same network. This test uses a
    generous threshold (50/second) well below both figures, so it stays
    a real regression guard without being flaky on slower CI hardware."""
    sim = _init_simulation(_config(tmp_path))
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        clone_simulator(sim)
    elapsed = time.perf_counter() - start
    rate = iterations / elapsed
    assert rate > 50, f"expected > 50 clones/sec, got {rate:.1f}/sec -- the memo optimization may have regressed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: FAIL — `ModuleNotFoundError` (module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/mcts.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/mcts.py tests/test_mcts.py
git commit -m "feat: add clone_simulator - memo-optimized Simulator cloning for MCTS rollouts"
```

---

## Task 2: Opportunistic rollout policy + reward function

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/mcts.py`
- Modify: `tests/test_mcts.py`

**Interfaces:**
- Consumes: `component_due`, `needs_maintenance`, `maintenance_action_for`, `segments_already_due`, `days_until_next_threshold`, `_move_priority` (all from `.greedy`); `_execute_decision` (from `..auto_planner` — the private function `auto_planner.py` already uses in its own run loop); `clone_simulator` (Task 1).
- Produces:
  - `PROXIMITY_RATIO: float = 0.7`, `ROLLOUT_MAX_DAYS: int = 45`, `OPPORTUNISTIC_BONUS_WEIGHT: float = 5.0`, `WEIGHT_COVERAGE: float = 10.0`, `WEIGHT_TRAVEL: float = 1.0` (module-level constants — internal only, never exposed in config/UI).
  - `opportunistic_needs_maintenance(segments, ratio: float = PROXIMITY_RATIO) -> bool`
  - `opportunistic_maintenance_action_for(segments, ratio: float = PROXIMITY_RATIO) -> str`
  - `opportunistic_rollout_decision(sim: Simulator, *, proximity_ratio: float = PROXIMITY_RATIO) -> StepDecision`
  - `run_rollout(sim: Simulator, *, max_days: int = ROLLOUT_MAX_DAYS, proximity_ratio: float = PROXIMITY_RATIO) -> Tuple[Simulator, int]` — `sim` **must already be a clone** (this function mutates it in place); returns `(sim, opportunistic_count)`.
  - `evaluate_rollout_outcome(before: Simulator, after: Simulator, opportunistic_count: int, *, weight_coverage: float = WEIGHT_COVERAGE, weight_travel: float = WEIGHT_TRAVEL, weight_opportunistic_bonus: float = OPPORTUNISTIC_BONUS_WEIGHT) -> float` — higher is better.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_mcts.py
import json

from railroad_backend.services.auto_planner_strategies.mcts import (
    evaluate_rollout_outcome,
    opportunistic_maintenance_action_for,
    opportunistic_needs_maintenance,
    opportunistic_rollout_decision,
    run_rollout,
)
from src.simulator import Simulator
from src.utils.network_loader import load_network


def test_opportunistic_needs_maintenance_true_above_proximity_ratio_even_if_not_due(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 8.0  # 0.8 ratio -- above the 0.7 proximity threshold, but not yet due (>= 10.0)
    assert opportunistic_needs_maintenance((seg,)) is True


def test_opportunistic_needs_maintenance_false_below_proximity_ratio(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 5.0  # 0.5 ratio -- below the 0.7 threshold
    assert opportunistic_needs_maintenance((seg,)) is False


def test_opportunistic_maintenance_action_prefers_full_maintain_when_tangente_near_threshold(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 3.0
    seg.mtbt_threshold_tangente = 10.0
    seg.load_tangente = 8.0
    assert opportunistic_maintenance_action_for((seg,)) == "maintain"


def _chain_network_sim(tmp_path: Path) -> Simulator:
    """A-B-C corridor with generous daily traffic so segments accumulate
    load quickly during a rollout."""
    network_path = tmp_path / "chain.json"
    network_path.write_text(
        json.dumps(
            {
                "name": "Chain",
                "stations": [
                    {"name": "A", "can_turn": False},
                    {"name": "B", "can_turn": False},
                    {"name": "C", "can_turn": False},
                ],
                "segments": [
                    {
                        "name": "A-B", "start": "A", "end": "B", "length_km": 1.0,
                        "mtbt_threshold_curva": 10.0, "mtbt_threshold_tangente": 30.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                    {
                        "name": "B-C", "start": "B", "end": "C", "length_km": 1.0,
                        "mtbt_threshold_curva": 10.0, "mtbt_threshold_tangente": 30.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01,2025-02,2025-03\nA-B,1.0,1.0,1.0\nB-C,1.0,1.0,1.0\n")
    sim = Simulator(load_network(network_path))
    from railroad_backend.domain.schedule import build_daily_map
    sim.init_machine(
        start_station_name="A", facing_station_name="B", start_year=2025,
        daily_map=build_daily_map(csv_path, 2025, 2025),
    )
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 9.0  # already past the 0.7 ratio (7.0), not yet due (10.0)
    return sim


def test_opportunistic_rollout_decision_maintains_a_near_threshold_segment_while_passing(tmp_path):
    sim = _chain_network_sim(tmp_path)
    decision = opportunistic_rollout_decision(sim)
    assert decision.kind == "move"
    assert any(seg.name == "A-B" for seg in decision.segments)
    assert decision.action in {"maintain", "maintain_curves"}


def test_run_rollout_counts_opportunistic_maintenance_actions(tmp_path):
    sim = clone_simulator(_chain_network_sim(tmp_path))
    _, opportunistic_count = run_rollout(sim, max_days=10)
    assert opportunistic_count >= 1


def test_evaluate_rollout_outcome_rewards_more_opportunistic_maintenance(tmp_path):
    before = _chain_network_sim(tmp_path)
    after_more = clone_simulator(before)
    after_fewer = clone_simulator(before)
    value_more = evaluate_rollout_outcome(before, after_more, opportunistic_count=3)
    value_fewer = evaluate_rollout_outcome(before, after_fewer, opportunistic_count=0)
    assert value_more > value_fewer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: FAIL — the new names don't exist in `mcts.py` yet.

- [ ] **Step 3: Add the implementation to `mcts.py`**

```python
# append to src/railroad_backend/services/auto_planner_strategies/mcts.py
from typing import Tuple

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE

from ...services.auto_planner import _execute_decision
from .base import StepDecision
from .greedy import (
    _move_priority,
    days_until_next_threshold,
    needs_maintenance,
    segments_already_due,
)

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
        options = sim.get_possible_moves() or sim.get_all_moves_any_direction()
        if not options:
            if sim.current_station and sim.current_station.can_turn:
                return StepDecision(kind="turn")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/mcts.py tests/test_mcts.py
git commit -m "feat: add opportunistic rollout policy and reward function for MCTS"
```

---

## Task 3: MCTS tree and search algorithm

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/mcts.py`
- Modify: `tests/test_mcts.py`

**Interfaces:**
- Consumes: `clone_simulator`, `run_rollout`, `evaluate_rollout_outcome` (Task 1-2); `needs_maintenance`, `maintenance_action_for` (from `.greedy`); `_execute_decision` (from `..auto_planner`).
- Produces:
  - `DecisionKey = Tuple` — a hashable, plain-data signature for a `StepDecision` (see the object-identity gotcha in Global Constraints). Shape: `("move", segment_names: Tuple[str, ...], next_station_name: str, action: str)` | `("wait", wait_days: int)` | `("turn",)` | `("none",)`.
  - `decision_key(decision: StepDecision) -> DecisionKey`
  - `resolve_decision(sim: Simulator, key: DecisionKey) -> StepDecision` — reconstructs a real, executable `StepDecision` against `sim`'s **own** `Segment`/`Station` objects, looked up by name. This is the only safe way to execute a cached tree decision against a simulator instance it wasn't originally computed from.
  - `enumerate_decision_keys(sim: Simulator) -> List[DecisionKey]` — every real decision available from `sim`'s current state: every reachable move, annotated with the maintenance action the same way the rollout policy picks one (due first, else opportunistic-proximity, else plain move — so the root child MCTS finally returns is already consistent with the tree it searched), a turn when available, a wait when nothing else applies.
  - `@dataclass class MCTSNode`: `decision_key: Optional[DecisionKey]`, `parent: Optional[MCTSNode]`, `children: Dict[DecisionKey, MCTSNode]`, `visits: int`, `total_value: float`, `untried_keys: Optional[List[DecisionKey]]`. Method `mean_value -> float`, method `ucb1(exploration_constant: float) -> float`.
  - `search(root_sim: Simulator, root: Optional[MCTSNode] = None, *, time_budget_s: Optional[float] = None, max_iterations: Optional[int] = None, exploration_constant: float = math.sqrt(2), rollout_max_days: int = ROLLOUT_MAX_DAYS, proximity_ratio: float = PROXIMITY_RATIO) -> Tuple[StepDecision, MCTSNode]` — exactly one of `time_budget_s`/`max_iterations` must be given (tests use `max_iterations` for determinism; production uses `time_budget_s`). Returns `(decision, new_root)` where `new_root` is the child corresponding to the chosen decision, detached from its parent (re-rooted, ready for reuse on the next call).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_mcts.py
import math

from railroad_backend.services.auto_planner_strategies.mcts import (
    MCTSNode,
    decision_key,
    enumerate_decision_keys,
    resolve_decision,
    search,
)


def test_decision_key_and_resolve_decision_round_trip_across_clones(tmp_path):
    """The core object-identity guard: a key computed against one clone
    must resolve correctly against a *different* clone's own objects."""
    sim_a = _chain_network_sim(tmp_path)
    options = sim_a.get_possible_moves() or sim_a.get_all_moves_any_direction()
    segments, next_station = options[0]
    original = StepDecision(kind="move", segments=segments, next_station=next_station, action="move")
    key = decision_key(original)

    sim_b = clone_simulator(sim_a)
    resolved = resolve_decision(sim_b, key)
    assert resolved.kind == "move"
    # The resolved segments/station must belong to sim_b, not sim_a.
    assert all(seg in sim_b.segments for seg in resolved.segments)
    assert resolved.next_station in sim_b.stations.values()
    assert all(seg not in sim_a.segments or seg is seg for seg in resolved.segments)  # sanity: no crash
    assert resolved.next_station is not next_station


def test_enumerate_decision_keys_includes_maintenance_action_when_due(tmp_path):
    sim = _chain_network_sim(tmp_path)
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 10.0  # already due
    keys = enumerate_decision_keys(sim)
    move_keys = [k for k in keys if k[0] == "move" and k[1] == ("A-B",)]
    assert move_keys
    assert move_keys[0][3] in {"maintain", "maintain_curves"}


def test_search_converges_to_visiting_the_only_due_segment_first(tmp_path):
    """Deterministic scenario: A-B is already due, B-C is not. With a
    reasonable iteration budget, the root's most-visited child must be
    the move toward B (the due segment)."""
    sim = _chain_network_sim(tmp_path)
    decision, _ = search(sim, max_iterations=200, exploration_constant=math.sqrt(2))
    assert decision.kind == "move"
    assert any(seg.name == "A-B" for seg in decision.segments)


def test_search_reuses_the_provided_root_without_error(tmp_path):
    sim = _chain_network_sim(tmp_path)
    decision, new_root = search(sim, max_iterations=50)
    assert isinstance(new_root, MCTSNode)
    assert new_root.parent is None
    # Feed the reused root back into a second search on the same state --
    # must not raise and must still return a valid decision.
    decision2, new_root2 = search(sim, new_root, max_iterations=50)
    assert decision2.kind in {"move", "wait", "turn", "none"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: FAIL — `decision_key`, `resolve_decision`, `enumerate_decision_keys`, `MCTSNode`, `search` don't exist yet.

- [ ] **Step 3: Add the implementation to `mcts.py`**

```python
# append to src/railroad_backend/services/auto_planner_strategies/mcts.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts.py -v`
Expected: 13 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/mcts.py tests/test_mcts.py
git commit -m "feat: add MCTS tree (UCB1 selection, expansion, rollout, backpropagation) with cross-clone-safe decision keys"
```

---

## Task 4: `MCTSStrategy` — public strategy with tree reuse, registered

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/mcts_strategy.py`
- Test: `tests/test_mcts_strategy.py`
- Modify: `src/railroad_backend/services/auto_planner.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: `search`, `MCTSNode`, `PROXIMITY_RATIO`, `ROLLOUT_MAX_DAYS` (Task 3, `.mcts`); `AutoPlanStrategy`, `StepDecision` (`.base`).
- Produces: `class MCTSStrategy(AutoPlanStrategy)`, constructor `__init__(self, *, time_budget_s: float = 10.0, exploration_constant: float = math.sqrt(2), rollout_max_days: int = ROLLOUT_MAX_DAYS, proximity_ratio: float = PROXIMITY_RATIO)`. `STRATEGY_REGISTRY["mcts"] = MCTSStrategy`. `AutoPlanResult.strategy_name` can be `"mcts"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcts_strategy.py
"""Tests for MCTSStrategy: tree reuse across real decisions."""
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.mcts_strategy import MCTSStrategy


def _config(tmp_path: Path) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_mcts_strategy_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = MCTSStrategy(time_budget_s=1.0)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}


def test_mcts_strategy_reuses_its_tree_across_consecutive_calls(tmp_path):
    """After the first call, the strategy should hold a non-empty reused
    root (proof the tree-reuse wiring is connected, not just that search()
    works in isolation, which Task 3 already covers)."""
    sim = _init_simulation(_config(tmp_path))
    strategy = MCTSStrategy(time_budget_s=1.0)
    strategy.decide_next_action(sim)
    assert strategy._root is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the strategy**

```python
# src/railroad_backend/services/auto_planner_strategies/mcts_strategy.py
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
```

- [ ] **Step 4: Run the strategy tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcts_strategy.py -v`
Expected: 2 passed.

- [ ] **Step 5: Register the strategy in `auto_planner.py`**

Add the import: `from .auto_planner_strategies.mcts_strategy import MCTSStrategy`.

Add `"mcts": MCTSStrategy` to `STRATEGY_REGISTRY`.

In `_resolve_strategy`, add a branch alongside the existing `rolling_ilp`/`simulated_annealing` ones:

```python
    if config.strategy == "mcts":
        return MCTSStrategy()
```

No new `AutoPlanConfig` field: per spec, MCTS's time budget (10s default), UCB1 exploration constant, rollout depth, and proximity ratio are all `MCTSStrategy` constructor defaults, exactly like `SimulatedAnnealingStrategy`'s iterations/temperature/cooling — internal, not exposed at the config-object level either, only `strategy="mcts"` is new surface.

- [ ] **Step 6: Write the integration test**

```python
# append to tests/test_integration.py, inside the AUTO PLANNING WORKFLOW TESTS section
def test_auto_plan_mcts_strategy_runs_end_to_end(tmp_path):
    """MCTS strategy produces a valid result on a tiny network. Uses the
    real 10s-per-decision default budget (no config override exists, per
    spec's no-new-config-field constraint) with a single step, so this
    test costs ~10s of real wall-clock time -- an accepted one-off cost,
    not a pattern to repeat elsewhere in the suite."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")

    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
        strategy="mcts",
    )
    result = run_auto_plan(config)
    assert result.strategy_name == "mcts"
    assert isinstance(result, AutoPlanResult)
```

- [ ] **Step 7: Run the integration test, then the full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k mcts -v`
Expected: 1 passed (takes ~10s).

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions.

- [ ] **Step 8: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/mcts_strategy.py src/railroad_backend/services/auto_planner.py tests/test_mcts_strategy.py tests/test_integration.py
git commit -m "feat: register MCTSStrategy with tree reuse across real decisions (no UI exposure beyond time budget)"
```

---

## Task 5: Real-network validation

**Files:** none (validation-only task, no code changes).

- [ ] **Step 1: Re-run the step-by-step diagnostic against the real network**

Write a throwaway script (scratchpad, not the repo) that builds the real `Simulator` via `_init_simulation` (same as `tests/test_mcts.py`'s helpers) against `network_20251223_115340.json` / `data/mtbt_schedule.csv` (ZTO start, ZCZ facing, 2026-2027, 2º KLD), constructs `MCTSStrategy(time_budget_s=3.0)` directly (short budget for a quick manual check, not the production 10s default — no `AutoPlanConfig` field exists for this, by design, so instantiate the strategy directly rather than going through `run_auto_plan`), and manually loops `decision = strategy.decide_next_action(sim); _execute_decision(sim, decision)` ~20 times, printing each decision (station, action, segment).

Expected: no repeating station-pair oscillation; segments should get maintained noticeably before reaching extreme severity (this strategy's whole point is closing that gap), and some maintenance actions should occur on segments that were not yet strictly "due" (opportunistic grouping visibly firing) — watch for `action` values other than a plain `move` on segments whose load was below their threshold at the time.

- [ ] **Step 2: If something looks wrong, stop and investigate before Task 6**

Do not proceed to the expensive multi-run study (Task 6) on top of an MCTS strategy that's visibly misbehaving in a 20-step manual check — that would just waste computation reproducing a known problem at scale. If the 20-step check looks reasonable, proceed.

---

## Task 6: Compare MCTS against Greedy/ILP/SA *and* the real manual plan

**Files:**
- Modify: `scripts/compare_auto_strategies.py`
- Create (by running the script): updated `docs/2026-08-11-auto-planner-algorithm-study.md`

**Interfaces:**
- Consumes: `run_auto_plan_from_args(..., strategy="mcts")` (no extra MCTS kwargs — the strategy has no exposed config fields, per Task 4); `railroad_backend.services.manual_planner.ManualPlanConfig`/`replay_manual_plan` (already used earlier this session to replay `data/saved_plans.json`'s `"Plano - Nos (v2 segment_actions)"` against the real network for the manual-vs-automatic comparison).

- [ ] **Step 1: Add an MCTS row and a manual-plan row to the study script**

Add to `scripts/compare_auto_strategies.py`: an `_run_mcts()` function mirroring `_run_ilp()`/`_run_sa()` but calling `run_auto_plan_from_args(..., strategy="mcts")` with no extra keyword arguments (MCTS exposes nothing else — the 10s time budget, exploration constant, rollout depth, and proximity ratio are all internal `MCTSStrategy` defaults); included once per window-days value the script already loops over is unnecessary here (MCTS doesn't take a window parameter) — call it once, and add its row to the summary table. Also add a `_replay_manual_plan()` function that loads `data/saved_plans.json`'s `"Plano - Nos (v2 segment_actions)"` entry, replays it via `ManualPlanConfig`/`replay_manual_plan` against the same real network, computes the same `_metrics(...)`-shaped dict (reuse the existing `_metrics()` helper by constructing an object with a `.simulator` attribute, or inline the same computation directly against the replay's `ManualPlanReplay.simulator`), and adds it as a reference row at the top of the summary table.

- [ ] **Step 2: Run the study**

Run: `.venv\Scripts\python.exe scripts\compare_auto_strategies.py` (run in the background — this now includes an MCTS run, which at a 10s-per-decision budget across hundreds of steps takes real wall-clock time; budget accordingly, likely longer than prior rounds' ~40 minutes).

- [ ] **Step 3: Review the report together with Bruno**

Read `docs/2026-08-11-auto-planner-algorithm-study.md` with Bruno, specifically comparing the MCTS row's "% of time on real maintenance" figure against the manual-plan row (81-93% was the measured human range) and against Greedy/ILP/SA (65-71%). This is the number that answers whether the new strategy actually closed the gap it was built for.

- [ ] **Step 4: Record the outcome**

Append an entry to `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` with the real headline numbers (including the manual-plan reference row), whether MCTS closed the gap, and whatever Bruno decides about next steps. Also update `E:\Projetos\SecondBrain\projetos\segundo-cerebro\pendencias-gerais-de-trabalho.md`: either move the "Auto Planner - exploração de novo algoritmo" entry to "Finalizados" (if Bruno confirms this closes the line of work) or update its "Em aberto" summary with the new state (if more work remains) — do not guess which; ask him.

- [ ] **Step 5: Commit**

```bash
git add scripts/compare_auto_strategies.py docs/2026-08-11-auto-planner-algorithm-study.md
git commit -m "docs: Auto Planner algorithm study - add MCTS strategy and real manual-plan reference row"
```

---

## Post-plan note for the implementer

This plan does not add a neural policy/value network (AlphaZero-style) or parallelize rollouts across threads/processes — both are explicitly out of scope per the spec, worth revisiting only if Task 6's comparison shows the rollout-heuristic-only MCTS underperforms and the 10-second budget is confirmed insufficient even with the memo-optimized clone.
