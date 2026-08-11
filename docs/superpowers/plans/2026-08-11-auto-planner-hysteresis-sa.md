# Auto Planner: Commitment Hysteresis + Simulated Annealing Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill the rolling-horizon "nervousness" (oscillation) in `RollingHorizonILPStrategy` with a shared commit-until-invalidated base class, add a `SimulatedAnnealingStrategy` sharing the same objective and base, and produce a script + markdown report comparing Greedy / ILP+hysteresis / SA across multiple planning-horizon lengths on the real network — with **no UI changes**.

**Architecture:** A new `CommittedWindowStrategy` base class owns the "solve once, execute the cached plan until it's exhausted or invalidated" loop (the fix for nervousness, grounded in rolling-horizon "nervousness" literature — Jensen 1993, Heisig 2002, Kimms 1997). `RollingHorizonILPStrategy` is refactored to extend it, implementing only `_solve_window` via the existing CP-SAT `solve_window`. A new `solve_window_sa` (Simulated Annealing, same `WindowPlan` return type) backs a new `SimulatedAnnealingStrategy` extending the same base — zero duplication of the commit/execution logic between the two window-based strategies. A new script variant runs all three strategies across four planning-horizon lengths against the real network and writes a markdown report for human review.

**Tech Stack:** Same as the prior Auto Planner rounds — Python 3.10+, `networkx`, `ortools` (CP-SAT, unchanged), pure-Python Simulated Annealing (no new dependency), `pytest`.

## Global Constraints

- Repo: `E:\Projetos\Simulador de Esmerilhamento\railroad-maintenance-simulator`. Work directly on `master`, commit after every task, per this repo's established pattern.
- **No UI changes.** Do not touch `src/railroad_frontend/views/auto_simulation.py`, `src/railroad_frontend/views/comparison.py`, or `streamlit_app.py`'s Streamlit-facing code in this plan. The existing `ilp_*`-prefixed `AutoPlanConfig` fields and their UI wiring are untouched and keep working exactly as they do today — new config fields for the SA strategy get their own `sa_`-prefixed names instead of renaming the existing ones, specifically to avoid touching UI call sites this round.
- Simulated Annealing's internal search parameters (`iterations`, `initial_temperature`, `cooling_rate`) are never exposed through any UI — they're constructor/function arguments only, used by tests and the comparison script.
- Run `python -m pytest` (full suite) after every task — zero regressions is the established bar for this repo.
- `.venv\Scripts\python.exe` is this repo's real interpreter (matches every prior task in this session's plans).

---

## Task 1: `CommittedWindowStrategy` base class

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/committed_window.py`
- Test: `tests/test_committed_window_strategy.py`

**Interfaces:**
- Consumes: `StepDecision`/`AutoPlanStrategy` (`base.py`), `GreedyUrgencyStrategy`/`maintenance_action_for`/`needs_maintenance` (`greedy.py`), `DueCandidate`/`project_due_candidates` (`horizon.py`), `WindowPlan` (`rolling_ilp.py`), `build_travel_graph`/`shortest_travel_days` (`travel_graph.py`).
- Produces: `class CommittedWindowStrategy(AutoPlanStrategy, abc.ABC)` with constructor `__init__(self, *, window_days: int = 60)`, abstract method `_solve_window(self, candidates: List[DueCandidate], graph, start_station: str) -> WindowPlan`, and a concrete `decide_next_action(self, sim) -> StepDecision` that caches/replans per the rules below. Concrete subclasses only need to implement `_solve_window`.

This is the fix for "nervousness": instead of calling `_solve_window` on every real step, cache the resulting `WindowPlan` and keep executing it (popping the front stop once it's physically crossed) until it's exhausted, or a candidate that's due *right now* shows up that wasn't part of the cached plan's candidate set.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_committed_window_strategy.py
"""Tests for CommittedWindowStrategy: the shared hysteresis/commitment layer
that fixes rolling-horizon "nervousness" (oscillation between near-tied
replans)."""
import json
from pathlib import Path
from typing import List

from railroad_backend.services.auto_planner_strategies.committed_window import (
    CommittedWindowStrategy,
)
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan, WindowStop
from src.simulator import Simulator
from src.utils.network_loader import load_network


def _write_chain_network(path: Path) -> None:
    """A-B-C corridor, both segments start already due."""
    path.write_text(
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
                        "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                    {
                        "name": "B-C", "start": "B", "end": "C", "length_km": 1.0,
                        "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _chain_sim(tmp_path: Path, *, both_due: bool = True) -> Simulator:
    network_path = tmp_path / "chain.json"
    _write_chain_network(network_path)
    sim = Simulator(load_network(network_path))
    sim.init_machine(start_station_name="A", facing_station_name="B", start_year=2025)
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 10.0  # already past mtbt_threshold_curva=5.0
    if both_due:
        b_c = next(s for s in sim.segments if s.name == "B-C")
        b_c.load_curva = 10.0
    return sim


class _RecordingStrategy(CommittedWindowStrategy):
    """Test double: returns pre-scripted plans in order, records every call."""

    def __init__(self, scripted_plans: List[WindowPlan], **kwargs) -> None:
        super().__init__(**kwargs)
        self._scripted_plans = list(scripted_plans)
        self.solve_calls = 0

    def _solve_window(self, candidates, graph, start_station):
        self.solve_calls += 1
        return self._scripted_plans[self.solve_calls - 1]


def test_cached_plan_is_reused_without_replanning_while_still_valid(tmp_path):
    sim = _chain_sim(tmp_path, both_due=True)
    plan = WindowPlan(
        stops=[
            WindowStop(station_name="B", segment_name="A-B", arrival_day=1),
            WindowStop(station_name="C", segment_name="B-C", arrival_day=2),
        ],
        feasible=True,
    )
    strategy = _RecordingStrategy([plan])

    strategy.decide_next_action(sim)  # first call: solves, executes the A-B hop, pops it
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # second call: B-C still cached and still due -- no new solve
    assert strategy.solve_calls == 1


def test_replans_once_the_cached_plan_is_exhausted(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)
    first_plan = WindowPlan(stops=[WindowStop(station_name="B", segment_name="A-B", arrival_day=1)], feasible=True)
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([first_plan, second_plan])

    strategy.decide_next_action(sim)  # pops the only stop -- cache now empty
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # cache empty -- must replan
    assert strategy.solve_calls == 2


def test_replans_when_a_new_already_due_candidate_appears_outside_the_cached_plan(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)  # only A-B due at first
    # Plan with 2 stops so it is not exhausted by the first real hop.
    first_plan = WindowPlan(
        stops=[
            WindowStop(station_name="B", segment_name="A-B", arrival_day=1),
            WindowStop(station_name="C", segment_name="Z-not-really-due-yet", arrival_day=5),
        ],
        feasible=True,
    )
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([first_plan, second_plan])

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 1

    # B-C becomes due *now*, but it was never part of the cached plan's candidate set.
    b_c = next(s for s in sim.segments if s.name == "B-C")
    b_c.load_curva = 10.0

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 2, "a newly-due candidate outside the cached plan must force a replan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_committed_window_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '...committed_window'`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/committed_window.py
"""Shared "solve once, commit until invalidated" execution layer.

Rolling-horizon strategies that resolve a full planning model on every
single real step suffer from "nervousness" -- a documented phenomenon in
rolling-horizon/MRP scheduling (Jensen 1993, "Nervousness and Reorder
Policies in Rolling Horizon Environments"; Heisig 2002, "Nervousness in
Material Requirements Planning Systems"; Kimms 1997, "Rolling Planning
Horizon") where near-tied solutions flip between consecutive replans,
causing the machine to oscillate between two targets instead of ever
committing to either. Confirmed on the real network: `RollingHorizonILPStrategy`
looped between two adjacent stations for dozens of steps after servicing
both, because every step re-solved from scratch with no memory of the
previous plan (2026-08-11 diagnostic).

This base class caches the resolved `WindowPlan` and keeps executing it
until either the plan is exhausted, or a candidate that's due *right now*
turns up outside the set the cached plan was built from.
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, List, Optional, Set

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import DueCandidate, project_due_candidates
from .rolling_ilp import WindowPlan
from .travel_graph import build_travel_graph, shortest_travel_days

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
        if station is None:
            return self._fallback.decide_next_action(sim)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments)

        if self._should_replan(candidates):
            plan = self._solve_window(candidates, graph, station.name)
            self._cached_plan = plan
            self._cached_candidate_names = {c.segment_name for c in candidates}

        plan = self._cached_plan
        if plan is None or not plan.feasible or not plan.stops:
            self._cached_plan = None
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        target_segment_name = plan.stops[0].segment_name
        decision = self._next_real_move_toward(sim, graph, target_station)
        if decision.kind == "move" and any(seg.name == target_segment_name for seg in (decision.segments or ())):
            plan.stops.pop(0)
        return decision

    def _should_replan(self, candidates: List[DueCandidate]) -> bool:
        if self._cached_plan is None or not self._cached_plan.stops:
            return True
        newly_due = {c.segment_name for c in candidates if c.days_until_due == 0}
        return not newly_due.issubset(self._cached_candidate_names)

    def _next_real_move_toward(self, sim: "Simulator", graph, target_station: str) -> StepDecision:
        options = sim.get_possible_moves()
        if not options:
            return self._fallback.decide_next_action(sim)

        def remaining_distance(option) -> float:
            segments, next_station = option
            distance = shortest_travel_days(graph, next_station.name, target_station)
            return float("inf") if distance is None else distance

        segments, next_station = min(options, key=remaining_distance)
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["CommittedWindowStrategy"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_committed_window_strategy.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/committed_window.py tests/test_committed_window_strategy.py
git commit -m "feat: add CommittedWindowStrategy - fixes rolling-horizon nervousness via plan caching"
```

---

## Task 2: Refactor `RollingHorizonILPStrategy` onto `CommittedWindowStrategy`

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py`
- Modify: `tests/test_rolling_horizon_ilp_strategy.py`

**Interfaces:**
- Consumes: `CommittedWindowStrategy` (Task 1).
- Produces: `RollingHorizonILPStrategy` keeps its existing public constructor signature (`window_days`, `weight_coverage`, `weight_travel`, `weight_proximity`, `time_limit_s`) and `decide_next_action` behavior — this is a pure internal refactor, not a behavior change to its public interface. `AutoPlanConfig`/`run_auto_plan_from_args`/`STRATEGY_REGISTRY` in `auto_planner.py` are untouched (still construct it the same way).

The whole point of Task 1 was to let this class shed its own `decide_next_action`/`_next_real_move_toward` and just plug its CP-SAT call into `_solve_window`.

- [ ] **Step 1: Confirm the pre-refactor baseline passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_horizon_ilp_strategy.py -v`
Expected: 3 passed (the suite from the prior round, including the two 2026-08-11 bug-fix regression tests).

- [ ] **Step 2: Rewrite `rolling_horizon_ilp.py` to extend `CommittedWindowStrategy`**

```python
# src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py
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
```

- [ ] **Step 3: Update the existing test file's patch targets**

`tests/test_rolling_horizon_ilp_strategy.py` currently patches `railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp.solve_window` — this import still lives in the same module after the refactor (`from .rolling_ilp import WindowPlan, solve_window`), so the patch target string is unchanged. Open the file and re-read it against the new class before touching anything; if `_next_real_move_toward` was referenced directly anywhere in the test (it shouldn't be — the tests call `decide_next_action`), update the reference to go through `CommittedWindowStrategy._next_real_move_toward` instead, since that method moved.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_horizon_ilp_strategy.py -v`
Expected: 3 passed, unchanged from Step 1 baseline (this refactor must not change any test's outcome).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions (this includes `tests/test_integration.py::test_auto_plan_rolling_ilp_strategy_runs_end_to_end`, which exercises this class through the full `run_auto_plan` path).

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py tests/test_rolling_horizon_ilp_strategy.py
git commit -m "refactor: RollingHorizonILPStrategy extends CommittedWindowStrategy (fixes nervousness)"
```

---

## Task 3: `solve_window_sa` — Simulated Annealing window solver

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/simulated_annealing.py`
- Test: `tests/test_simulated_annealing.py`

**Interfaces:**
- Consumes: `DueCandidate` (`horizon.py`), `WindowPlan`/`WindowStop` (`rolling_ilp.py`), `shortest_travel_days` (`travel_graph.py`).
- Produces: `solve_window_sa(candidates: List[DueCandidate], graph, start_station: str, *, weight_coverage: float, weight_travel: float, weight_proximity: float, iterations: int = 2000, initial_temperature: float = 100.0, cooling_rate: float = 0.995, seed: Optional[int] = None) -> WindowPlan` — same return type as `rolling_ilp.solve_window`, so it plugs into `CommittedWindowStrategy` without any changes to that class.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulated_annealing.py
"""Tests for the Simulated Annealing rolling-horizon window solver."""
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.simulated_annealing import solve_window_sa
from railroad_backend.services.auto_planner_strategies.travel_graph import build_travel_graph
from src.models import Segment, Station


def test_solve_window_sa_empty_candidates_returns_feasible_empty_plan():
    a = Station(name="A")
    seg = Segment(name="A-A", start_station=a, end_station=a, move_time_days=1, maintenance_time_days=1)
    graph = build_travel_graph([seg])
    plan = solve_window_sa([], graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1)
    assert plan.feasible
    assert plan.stops == []


def test_solve_window_sa_skips_unreachable_candidate_instead_of_failing():
    a, b = Station(name="A"), Station(name="B")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    graph = build_travel_graph([seg_ab])
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=5, service_days=1),
        DueCandidate(segment_name="ghost", station_name="Nowhere", days_until_due=1, service_days=1),
    ]
    plan = solve_window_sa(candidates, graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1, seed=42)
    assert plan.feasible
    visited = [stop.segment_name for stop in plan.stops]
    assert "A-B" in visited
    assert "ghost" not in visited


def test_solve_window_sa_prioritizes_already_due_candidate_over_cheaper_route():
    """Mirrors the CP-SAT regression test (test_rolling_ilp.py) with the same
    D/X/Y graph and weights: X is already due and reachable only by a more
    expensive direct route; Y is not urgent but sits on a cheaper detour that
    would delay X. X must still be visited first."""
    d, x, y = Station(name="D"), Station(name="X"), Station(name="Y")
    seg_dx = Segment(name="D-X", start_station=d, end_station=x, move_time_days=3, maintenance_time_days=1)
    seg_dy = Segment(name="D-Y", start_station=d, end_station=y, move_time_days=1, maintenance_time_days=1)
    seg_xy = Segment(name="X-Y", start_station=x, end_station=y, move_time_days=10, maintenance_time_days=1)
    graph = build_travel_graph([seg_dx, seg_dy, seg_xy])

    candidates = [
        DueCandidate(segment_name="D-X", station_name="X", days_until_due=0, service_days=1),
        DueCandidate(segment_name="D-Y", station_name="Y", days_until_due=1000, service_days=1),
    ]
    plan = solve_window_sa(
        candidates, graph, start_station="D",
        weight_coverage=100.0, weight_travel=1.0, weight_proximity=0.0,
        seed=7,
    )
    assert plan.feasible
    visited = [stop.segment_name for stop in plan.stops]
    assert visited[0] == "D-X", f"expected already-due D-X visited first, got order {visited}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simulated_annealing.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/simulated_annealing.py
"""Simulated Annealing solver for a single rolling-horizon planning window.

Same objective as the CP-SAT solver (rolling_ilp.py): minimize a weighted
sum of lateness (visiting an already-due candidate late), earliness
(visiting well before it's due -- wasted MTBT life), and total travel. Same
`WindowPlan` return type, so it plugs into `CommittedWindowStrategy`
unchanged. Search parameters (iterations/temperature/cooling) are internal
to this module -- never exposed through any UI or persisted config.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .rolling_ilp import WindowPlan, WindowStop
from .travel_graph import shortest_travel_days

if TYPE_CHECKING:
    import networkx as nx

    from .horizon import DueCandidate


def _evaluate_tour(
    order: List[str],
    candidates_by_name: Dict[str, "DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
) -> Tuple[float, List[WindowStop]]:
    day = 0
    current = start_station
    total_travel = 0
    penalty = 0.0
    stops: List[WindowStop] = []
    for name in order:
        candidate = candidates_by_name[name]
        travel = shortest_travel_days(graph, current, candidate.station_name)
        if travel is None:
            return math.inf, []
        day += travel
        total_travel += travel
        lateness = max(0, day - candidate.days_until_due)
        earliness = max(0, candidate.days_until_due - day)
        penalty += weight_coverage * lateness + weight_proximity * earliness
        stops.append(WindowStop(station_name=candidate.station_name, segment_name=candidate.segment_name, arrival_day=day))
        current = candidate.station_name
    cost = weight_travel * total_travel + penalty
    return cost, stops


def _construct_initial_order(
    candidates: List["DueCandidate"], graph: "nx.DiGraph", start_station: str
) -> List[str]:
    """Nearest-due-first greedy construction, only ever stepping to a
    reachable candidate -- guarantees the initial tour is feasible."""
    remaining = {c.segment_name: c for c in candidates}
    order: List[str] = []
    current = start_station
    while remaining:
        best_name: Optional[str] = None
        best_key: Optional[Tuple[int, int]] = None
        for name, candidate in remaining.items():
            travel = shortest_travel_days(graph, current, candidate.station_name)
            if travel is None:
                continue
            key = (candidate.days_until_due, travel)
            if best_key is None or key < best_key:
                best_key = key
                best_name = name
        if best_name is None:
            break  # nothing left is reachable from here
        order.append(best_name)
        current = remaining.pop(best_name).station_name
    return order


def solve_window_sa(
    candidates: List["DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    *,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
    iterations: int = 2000,
    initial_temperature: float = 100.0,
    cooling_rate: float = 0.995,
    seed: Optional[int] = None,
) -> WindowPlan:
    if not candidates:
        return WindowPlan(stops=[], feasible=True)

    reachable = [c for c in candidates if shortest_travel_days(graph, start_station, c.station_name) is not None]
    if not reachable:
        return WindowPlan(stops=[], feasible=True)

    candidates_by_name = {c.segment_name: c for c in reachable}
    rng = random.Random(seed)

    order = _construct_initial_order(reachable, graph, start_station)
    if not order:
        return WindowPlan(stops=[], feasible=True)

    def cost_of(candidate_order: List[str]) -> Tuple[float, List[WindowStop]]:
        return _evaluate_tour(
            candidate_order, candidates_by_name, graph, start_station,
            weight_coverage, weight_travel, weight_proximity,
        )

    current_order = list(order)
    current_cost, current_stops = cost_of(current_order)
    best_cost, best_stops = current_cost, current_stops
    temperature = initial_temperature

    for _ in range(iterations):
        if len(current_order) < 2:
            break
        i, j = rng.sample(range(len(current_order)), 2)
        candidate_order = list(current_order)
        candidate_order[i], candidate_order[j] = candidate_order[j], candidate_order[i]
        candidate_cost, candidate_stops = cost_of(candidate_order)

        delta = candidate_cost - current_cost
        accept = delta < 0 or (temperature > 1e-9 and rng.random() < math.exp(-delta / temperature))
        if accept:
            current_order, current_cost = candidate_order, candidate_cost
            if current_cost < best_cost:
                best_cost, best_stops = current_cost, candidate_stops
        temperature *= cooling_rate

    return WindowPlan(stops=best_stops, feasible=True)


__all__ = ["solve_window_sa"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simulated_annealing.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/simulated_annealing.py tests/test_simulated_annealing.py
git commit -m "feat: add Simulated Annealing rolling-horizon window solver"
```

---

## Task 4: `SimulatedAnnealingStrategy` + registration

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/simulated_annealing_strategy.py`
- Test: `tests/test_simulated_annealing_strategy.py`
- Modify: `src/railroad_backend/services/auto_planner.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: `CommittedWindowStrategy` (Task 1), `solve_window_sa` (Task 3).
- Produces: `class SimulatedAnnealingStrategy(CommittedWindowStrategy)`, constructor `__init__(self, *, window_days: int = 90, weight_coverage: float = 10.0, weight_travel: float = 1.0, weight_proximity: float = 0.5, iterations: int = 2000, initial_temperature: float = 100.0, cooling_rate: float = 0.995, seed: Optional[int] = None)`. `AutoPlanConfig` gains `sa_window_days: int = 90`, `sa_weight_coverage: float = 10.0`, `sa_weight_travel: float = 1.0`, `sa_weight_proximity: float = 0.5`, `sa_iterations: int = 2000`, `sa_initial_temperature: float = 100.0`, `sa_cooling_rate: float = 0.995`, `sa_seed: Optional[int] = None` — separate `sa_`-prefixed fields, not a rename of the existing `ilp_*` ones (see Global Constraints — no UI touch this round). `STRATEGY_REGISTRY["simulated_annealing"] = SimulatedAnnealingStrategy`. `run_auto_plan_from_args` gains the same 8 keyword arguments, passed through.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulated_annealing_strategy.py
"""Tests for SimulatedAnnealingStrategy."""
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.simulated_annealing_strategy import (
    SimulatedAnnealingStrategy,
)


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


def test_simulated_annealing_strategy_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = SimulatedAnnealingStrategy(seed=1, iterations=200)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simulated_annealing_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the strategy**

```python
# src/railroad_backend/services/auto_planner_strategies/simulated_annealing_strategy.py
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
```

- [ ] **Step 4: Register the strategy in `auto_planner.py`**

Add the import: `from .auto_planner_strategies.simulated_annealing_strategy import SimulatedAnnealingStrategy`.

Add `"simulated_annealing": SimulatedAnnealingStrategy` to `STRATEGY_REGISTRY`.

Add the 8 `sa_*` fields listed above to `AutoPlanConfig` (right after the `ilp_*` fields — `Optional` needs adding to the existing `typing` import for `sa_seed`, already imported in this file).

In `_resolve_strategy`, add a branch: when `config.strategy == "simulated_annealing"`, construct it with the config's `sa_*` fields:

```python
    if config.strategy == "simulated_annealing":
        return SimulatedAnnealingStrategy(
            window_days=config.sa_window_days,
            weight_coverage=config.sa_weight_coverage,
            weight_travel=config.sa_weight_travel,
            weight_proximity=config.sa_weight_proximity,
            iterations=config.sa_iterations,
            initial_temperature=config.sa_initial_temperature,
            cooling_rate=config.sa_cooling_rate,
            seed=config.sa_seed,
        )
```

(alongside the existing `if config.strategy == "rolling_ilp":` branch — both come before the final `return strategy_cls()` fallback for `"greedy"`.)

Add the same 8 keyword arguments to `run_auto_plan_from_args`, passed through to `AutoPlanConfig(...)`.

- [ ] **Step 5: Write the integration test**

```python
# append to tests/test_integration.py, inside the AUTO PLANNING WORKFLOW TESTS section
def test_auto_plan_simulated_annealing_strategy_runs_end_to_end(tmp_path):
    """Simulated Annealing strategy produces a valid result on a tiny network."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")

    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=5,
        strategy="simulated_annealing",
        sa_iterations=200,
        sa_seed=1,
    )
    result = run_auto_plan(config)
    assert result.strategy_name == "simulated_annealing"
    assert isinstance(result, AutoPlanResult)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simulated_annealing_strategy.py tests/test_integration.py -v`
Expected: all pass, including the 2 new tests.

- [ ] **Step 7: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions.

- [ ] **Step 8: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/simulated_annealing_strategy.py src/railroad_backend/services/auto_planner.py tests/test_simulated_annealing_strategy.py tests/test_integration.py
git commit -m "feat: register SimulatedAnnealingStrategy (no UI exposure, sa_* config fields only)"
```

---

## Task 5: Extend the comparison script into a multi-horizon study with a markdown report

**Files:**
- Modify: `scripts/compare_auto_strategies.py`

**Interfaces:**
- Consumes: `run_auto_plan_from_args` with `strategy` in `{"greedy", "rolling_ilp", "simulated_annealing"}`, `ilp_window_days`/`sa_window_days`, and (for SA) `sa_seed`.
- Produces: no new importable interfaces — this script becomes a study runner that writes `docs/2026-08-11-auto-planner-algorithm-study.md`.

No automated test for this task (it's a reporting script, mirroring the pattern of `scripts/overnight_manual_route_fuzz.py` from the Manual Route campaign) — verified by actually running it in Task 6.

- [ ] **Step 1: Rewrite the script**

```python
# scripts/compare_auto_strategies.py
"""Study script: run Greedy / Rolling-horizon ILP (with commitment) /
Simulated Annealing against the real network across several planning
horizons, and write a markdown report for human review. Not part of the
pytest suite -- run manually:
.venv\\Scripts\\python.exe scripts\\compare_auto_strategies.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from railroad_backend.services.auto_planner import run_auto_plan_from_args  # noqa: E402

NETWORK_FILE = Path(__file__).resolve().parent.parent / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE_CSV = Path(__file__).resolve().parent.parent / "data" / "mtbt_schedule.csv"
REPORT_FILE = Path(__file__).resolve().parent.parent / "docs" / "2026-08-11-auto-planner-algorithm-study.md"

WINDOW_DAYS = [60, 90, 120, 180]
SA_SEEDS = [1, 2, 3]
STEPS = 400
COMMON_KWARGS = dict(
    csv_path=SCHEDULE_CSV,
    start_station="ZTO",
    facing_station="ZCZ",
    start_year=2026,
    end_year=2027,
    steps=STEPS,
    second_kld=True,
    network_source=NETWORK_FILE,
)


def _metrics(result) -> Dict[str, Any]:
    sim = result.simulator
    idle = getattr(sim, "idle_days_total", 0)
    total = sim.movement_days_total + sim.maintenance_days_total + idle
    over_threshold = 0
    for seg in sim.segments:
        if seg.mtbt_threshold_curva and seg.load_curva >= seg.mtbt_threshold_curva:
            over_threshold += 1
        if seg.mtbt_threshold_tangente and seg.load_tangente >= seg.mtbt_threshold_tangente:
            over_threshold += 1
    return {
        "stop_reason": result.stop_reason,
        "steps": len(sim.steps),
        "maintenance_count": sim.maintenance_count,
        "movement_days": sim.movement_days_total,
        "maintenance_days": sim.maintenance_days_total,
        "idle_days": idle,
        "total_days": total,
        "segments_over_threshold_at_end": over_threshold,
    }


def _run_greedy() -> Dict[str, Any]:
    result = run_auto_plan_from_args(**COMMON_KWARGS, strategy="greedy")
    return _metrics(result)


def _run_ilp(window_days: int) -> Dict[str, Any]:
    result = run_auto_plan_from_args(
        **COMMON_KWARGS, strategy="rolling_ilp",
        ilp_window_days=window_days, ilp_weight_coverage=10.0, ilp_weight_travel=1.0,
        ilp_weight_proximity=0.5, ilp_time_limit_s=5.0,
    )
    return _metrics(result)


def _run_sa(window_days: int, seed: int) -> Dict[str, Any]:
    result = run_auto_plan_from_args(
        **COMMON_KWARGS, strategy="simulated_annealing",
        sa_window_days=window_days, sa_weight_coverage=10.0, sa_weight_travel=1.0,
        sa_weight_proximity=0.5, sa_iterations=2000, sa_seed=seed,
    )
    return _metrics(result)


def _format_row(label: str, m: Dict[str, Any]) -> str:
    return (
        f"| {label} | {m['stop_reason']} | {m['steps']} | {m['maintenance_count']} | "
        f"{m['movement_days']} | {m['maintenance_days']} | {m['idle_days']} | {m['total_days']} | "
        f"{m['segments_over_threshold_at_end']} |"
    )


def main() -> None:
    lines: List[str] = [
        "# Auto Planner algorithm study — Greedy vs Rolling-horizon ILP vs Simulated Annealing",
        "",
        f"Real network: `{NETWORK_FILE.name}`, ZTO→ZCZ, 2026–2027, 2º KLD, {STEPS} steps.",
        "",
        "## Summary table",
        "",
        "| Strategy | stop_reason | steps | maint. actions | movement days | maint. days | idle days | total days | segments over threshold |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    greedy_metrics = _run_greedy()
    lines.append(_format_row("Greedy", greedy_metrics))

    for window in WINDOW_DAYS:
        ilp_metrics = _run_ilp(window)
        lines.append(_format_row(f"Rolling ILP (window={window}d)", ilp_metrics))

        sa_results = [_run_sa(window, seed) for seed in SA_SEEDS]
        for seed, m in zip(SA_SEEDS, sa_results):
            lines.append(_format_row(f"Simulated Annealing (window={window}d, seed={seed})", m))
        totals = [m["total_days"] for m in sa_results]
        maint = [m["maintenance_count"] for m in sa_results]
        lines.append(
            f"| Simulated Annealing (window={window}d) min/avg/max | - | - | "
            f"{min(maint)}/{sum(maint) / len(maint):.1f}/{max(maint)} | - | - | - | "
            f"{min(totals)}/{sum(totals) / len(totals):.1f}/{max(totals)} | - |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Greedy has no planning window (1-hop lookahead), listed once for reference against every ILP/SA row."
    )
    lines.append(
        "- Simulated Annealing is stochastic: 3 seeds per window are run and reported individually plus a min/avg/max summary row."
    )
    lines.append(
        "- `segments_over_threshold_at_end` counts curva+tangente components still over their MTBT threshold when the run stops -- lower is better coverage."
    )

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/compare_auto_strategies.py
git commit -m "test: extend comparison script into a multi-horizon study with markdown report"
```

---

## Task 6: Run the study and review with Bruno

**Files:**
- Create (by running the script, not by hand): `docs/2026-08-11-auto-planner-algorithm-study.md`
- Modify: `SecondBrain/projetos/simulador-esmerilhamento/decisoes.md` (outside this repo)

- [ ] **Step 1: Run the study script**

Run: `.venv\Scripts\python.exe scripts\compare_auto_strategies.py`

This runs Greedy once, plus ILP and 3-seeded SA across 4 window sizes (60/90/120/180 days) — 1 + 4×(1+3) = 17 full `run_auto_plan_from_args` calls at 400 steps each. Budget real wall-clock time for this (the Task 12 sanity check from the prior round measured roughly 1.2s/step for the ILP strategy at 400 steps ≈ 8 minutes per run; run this in the background with a generous timeout, expect it to take well over an hour in total across all 17 runs).

- [ ] **Step 2: Review the report together with Bruno**

Read `docs/2026-08-11-auto-planner-algorithm-study.md` and the summary table it produced. This is a manual, human-in-the-loop step, not something to resolve unilaterally in code — the point of this whole round (per Bruno's explicit request) is to look at the generated plans and behavior before deciding whether any of this becomes a UI feature. Do not add UI code as part of this task regardless of what the numbers show; that's an explicit separate decision for a future round.

- [ ] **Step 3: Record the outcome**

Append an entry to `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` with the real headline numbers from the report table, whether the hysteresis fix visibly reduced oscillation compared to the pre-Task-1 diagnostic logs, and whatever Bruno decides about next steps (recalibrating weights, trying a wider/narrower window, moving toward a UI decision, or something else). Do not guess at his preference — this step happens together with him, same as the equivalent step in the prior two rounds.

- [ ] **Step 4: Commit the generated report**

```bash
git add docs/2026-08-11-auto-planner-algorithm-study.md
git commit -m "docs: Auto Planner algorithm study results - Greedy vs ILP+hysteresis vs Simulated Annealing"
```

---

## Post-plan note for the implementer

This plan produces **no UI changes** by design — confirmed explicitly with Bruno ("não gostaria de mais botões e configurações no nosso UI... o que quero é testar de fato os algoritmos"). Do not add a strategy selector, sliders, or any Streamlit-facing code for Simulated Annealing as part of this plan, even if the study results look good. That decision is explicitly deferred to a future round, after human review of the generated report.
