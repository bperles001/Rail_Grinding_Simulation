# Turn-Aware Travel Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the direction-blind travel-time graph with a `(station, direction)` state graph that correctly models CARREGADO/VAZIO facing restrictions and turn-station mechanics, and make `CommittedWindowStrategy`'s real execution follow an exact shortest path (including turns) instead of a greedy nearest-neighbor heuristic that can wander into unreachable pockets.

**Architecture:** `travel_graph.py` is rewritten around a state graph whose nodes are `(station_name, direction)` pairs, built by reusing the real `Simulator`'s own classification logic (`_get_possible_moves`, `_classify_directional_segment`) so the planning graph can never drift out of sync with what the engine actually allows. Two distance functions serve two different consumers: `shortest_travel_days` (exact, needs a known current direction — used by real execution) and `shortest_travel_days_any_direction` (approximate, direction-unknown — used inside the CP-SAT/SA models to rank candidates, a documented simplification). `CommittedWindowStrategy._next_real_move_toward` is rewritten to compute the real shortest path (via `shortest_path_first_step`) and execute only its first step, turn or move — correct by construction, since a true shortest path never omits a required turn.

**Tech Stack:** Same as prior rounds — Python 3.10+, `networkx`, `pytest`. No new dependency.

## Global Constraints

- Repo: `E:\Projetos\Simulador de Esmerilhamento\railroad-maintenance-simulator`. Work directly on `master`, commit after every task.
- **No UI changes** (same constraint as the prior round — this is still a "test the algorithms" phase, not a shipping decision).
- Run `python -m pytest` (full suite, 269 tests before this plan starts) after every task — zero regressions.
- `.venv\Scripts\python.exe` is this repo's real interpreter.
- Do **not** run `scripts/compare_auto_strategies.py` (the expensive multi-horizon study) until Task 5's real-network diagnostic confirms the ZQX↔ZIQ oscillation is gone — running it earlier would waste ~40+ minutes producing numbers still contaminated by the navigation bug.

---

## Task 1: Rewrite `travel_graph.py` around a turn-aware state graph

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/travel_graph.py`
- Modify: `tests/test_travel_graph.py`

**Interfaces:**
- Consumes: `_get_possible_moves` (`src/simulator/network_utils.py`), `_classify_directional_segment` (`src/simulator/core.py`) — reused directly, not reimplemented.
- Produces:
  - `State = Tuple[str, str]` (station_name, direction), `DIRECTIONS = ("CARREGADO", "VAZIO")`.
  - `PathStep` — frozen dataclass, `kind: str` ("turn" or "move"), `next_station: Optional[str]` (station name for "move", `None` for "turn").
  - `build_travel_graph(segments: Sequence[Segment], stations: Dict[str, Station]) -> nx.DiGraph` — **signature change**: now takes `stations` too (needed for turn edges and to enumerate every station's move options, not just ones with an outgoing segment reference).
  - `shortest_travel_days(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[int]` — **signature change**: `from_state` is now a `(station, direction)` tuple, not a bare station name.
  - `shortest_travel_days_any_direction(graph: nx.DiGraph, from_station: str, to_station: str) -> Optional[int]` — new function, direction-unknown approximation (min over the 4 direction combinations).
  - `shortest_path_first_step(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[PathStep]` — new function.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_travel_graph.py
"""Tests for the turn-aware Auto Planner travel-time state graph."""
from railroad_backend.services.auto_planner_strategies.travel_graph import (
    PathStep,
    build_travel_graph,
    shortest_path_first_step,
    shortest_travel_days,
    shortest_travel_days_any_direction,
)
from src.models import Segment, Station


def _linear_stations_and_segments():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=2)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=3)
    stations = {"A": a, "B": b, "C": c}
    return stations, [seg_ab, seg_bc]


def test_shortest_travel_days_single_hop_from_known_direction():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    # Plain (unsuffixed) segments have no direction restriction -- both
    # CARREGADO and VAZIO should reach B from A.
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "B") == 2
    assert shortest_travel_days(graph, ("A", "VAZIO"), "B") == 2


def test_shortest_travel_days_multi_hop_sums_weights():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "C") == 5


def test_directional_segment_only_reachable_in_its_own_direction():
    a, b = Station(name="A"), Station(name="B")
    # -LP suffix is always CARREGADO-only (see _classify_directional_segment).
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "B") == 1
    assert shortest_travel_days(graph, ("A", "VAZIO"), "B") is None


def test_turn_edge_costs_one_day_and_only_exists_at_can_turn_stations():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert graph.has_edge(("A", "CARREGADO"), ("A", "VAZIO"))
    assert graph.get_edge_data(("A", "CARREGADO"), ("A", "VAZIO"))["days"] == 1
    assert not graph.has_edge(("B", "CARREGADO"), ("B", "VAZIO"))


def test_reaching_a_direction_locked_segment_requires_a_turn_first():
    """A-B is CARREGADO-only. Starting at A in VAZIO, the only way to reach
    B is: turn at A (1 day) then take A-B (1 day) = 2 days total."""
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert shortest_travel_days(graph, ("A", "VAZIO"), "B") == 2


def test_shortest_travel_days_any_direction_takes_the_minimum():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    # From CARREGADO it's 1 day direct; from VAZIO it would need a turn (2 days).
    # The any-direction helper must report the cheaper of the two: 1.
    assert shortest_travel_days_any_direction(graph, "A", "B") == 1


def test_shortest_path_first_step_is_a_turn_when_a_turn_is_needed():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    step = shortest_path_first_step(graph, ("A", "VAZIO"), "B")
    assert step == PathStep(kind="turn", next_station=None)


def test_shortest_path_first_step_is_a_move_when_no_turn_is_needed():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    step = shortest_path_first_step(graph, ("A", "CARREGADO"), "C")
    assert step == PathStep(kind="move", next_station="B")


def test_shortest_path_first_step_none_when_already_there():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_path_first_step(graph, ("A", "CARREGADO"), "A") is None


def test_shortest_travel_days_unreachable_returns_none():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "Nowhere") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_travel_graph.py -v`
Expected: FAIL — `build_travel_graph()` currently takes 1 positional argument (`segments` only), and `shortest_path_first_step`/`shortest_travel_days_any_direction`/`PathStep` don't exist yet.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/travel_graph.py
"""Turn-aware travel-time graph for ranking candidates and for real execution.

Node = (station_name, direction), direction in {"CARREGADO", "VAZIO"} --
mirrors `Simulator.machine.global_direction`. Built by reusing the exact
functions the real Simulator uses to decide what's a legal move
(`_get_possible_moves`, `_classify_directional_segment`) -- never a parallel
reimplementation, which is what let this graph drift out of sync with real
execution in the first place (2026-08-11/12 diagnostic: the machine got
stuck oscillating between two stations because the old direction-blind
graph reported a target "reachable" that actually required a turn neither
the graph nor the execution logic knew about).

Two distance functions for two different consumers:
  - `shortest_travel_days`: the caller already knows its current
    (station, direction) -- used by real execution, where exactness matters.
  - `shortest_travel_days_any_direction`: no known direction -- used inside
    the CP-SAT/SA models to rank candidates against each other, where
    tracking direction as a tour-wide decision variable is out of scope for
    this round. Documented approximation: minimum over the 4 combinations
    of start/end direction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

import networkx as nx

from src.simulator.core import _classify_directional_segment
from src.simulator.network_utils import _get_possible_moves

if TYPE_CHECKING:
    from src.models import Segment, Station

DIRECTIONS: Tuple[str, str] = ("CARREGADO", "VAZIO")
State = Tuple[str, str]


@dataclass(frozen=True)
class PathStep:
    kind: str  # "turn" or "move"
    next_station: Optional[str]  # station name for "move"; None for "turn"


def build_travel_graph(segments: Sequence["Segment"], stations: Dict[str, "Station"]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for station in stations.values():
        for seg_tuple, other_station in _get_possible_moves(list(segments), station):
            weight = max(1, sum(int(s.move_time_days) for s in seg_tuple))
            direction = _classify_directional_segment(seg_tuple[-1], station.name)
            if direction is None:
                for d in DIRECTIONS:
                    graph.add_edge((station.name, d), (other_station.name, d), days=weight, kind="move")
            else:
                graph.add_edge((station.name, direction), (other_station.name, direction), days=weight, kind="move")
        if station.can_turn:
            carregado, vazio = (station.name, "CARREGADO"), (station.name, "VAZIO")
            graph.add_edge(carregado, vazio, days=1, kind="turn")
            graph.add_edge(vazio, carregado, days=1, kind="turn")
    return graph


def shortest_travel_days(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[int]:
    from_station, _ = from_state
    if from_station == to_station:
        return 0
    if from_state not in graph:
        return None
    best: Optional[int] = None
    for direction in DIRECTIONS:
        to_state = (to_station, direction)
        if to_state not in graph:
            continue
        try:
            length = nx.shortest_path_length(graph, from_state, to_state, weight="days")
        except nx.NetworkXNoPath:
            continue
        if best is None or length < best:
            best = length
    return best


def shortest_travel_days_any_direction(graph: nx.DiGraph, from_station: str, to_station: str) -> Optional[int]:
    if from_station == to_station:
        return 0
    best: Optional[int] = None
    for direction in DIRECTIONS:
        distance = shortest_travel_days(graph, (from_station, direction), to_station)
        if distance is None:
            continue
        if best is None or distance < best:
            best = distance
    return best


def shortest_path_first_step(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[PathStep]:
    from_station, _ = from_state
    if from_station == to_station:
        return None
    if from_state not in graph:
        return None
    best_length: Optional[int] = None
    best_path: Optional[list] = None
    for direction in DIRECTIONS:
        to_state = (to_station, direction)
        if to_state not in graph:
            continue
        try:
            length, path = nx.single_source_dijkstra(graph, from_state, to_state, weight="days")
        except nx.NetworkXNoPath:
            continue
        if best_length is None or length < best_length:
            best_length, best_path = length, path
    if not best_path or len(best_path) < 2:
        return None
    first_state, second_state = best_path[0], best_path[1]
    edge_data = graph.get_edge_data(first_state, second_state)
    if edge_data.get("kind") == "turn":
        return PathStep(kind="turn", next_station=None)
    return PathStep(kind="move", next_station=second_state[0])


__all__ = [
    "DIRECTIONS",
    "PathStep",
    "State",
    "build_travel_graph",
    "shortest_travel_days",
    "shortest_travel_days_any_direction",
    "shortest_path_first_step",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_travel_graph.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/travel_graph.py tests/test_travel_graph.py
git commit -m "feat: rewrite travel_graph as a turn-aware (station, direction) state graph"
```

---

## Task 2: Update `rolling_ilp.py` to the direction-unknown approximation

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/rolling_ilp.py`
- Modify: `tests/test_rolling_ilp.py`

**Interfaces:**
- Consumes: `shortest_travel_days_any_direction`, `build_travel_graph(segments, stations)` (Task 1).
- Produces: no change to `solve_window`'s public signature (still takes a `start_station: str` — the CP-SAT model never tracked direction, so nothing here changes except which travel_graph function it calls internally).

- [ ] **Step 1: Update the import and both call sites**

In `rolling_ilp.py`, replace `from .travel_graph import shortest_travel_days` with `from .travel_graph import shortest_travel_days_any_direction`, and replace both call sites (`shortest_travel_days(graph, start_station, candidate.station_name)` at line ~49, and `shortest_travel_days(graph, station_by_node[i], station_by_node[j])` at line ~74) with `shortest_travel_days_any_direction(graph, ..., ...)` (same arguments, just the renamed function).

- [ ] **Step 2: Update the test file's graph construction calls**

`tests/test_rolling_ilp.py` builds graphs via `build_travel_graph([seg_ab, seg_bc])` (old 1-arg signature) in `_three_node_graph()`, and via `build_travel_graph([seg_dx, seg_dy, seg_xy])` in `test_solve_window_prioritizes_already_due_candidate_over_cheaper_route`. Both need a `stations` dict as the second argument now. Update `_three_node_graph()`:

```python
def _three_node_graph():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=1, maintenance_time_days=1)
    stations = {"A": a, "B": b, "C": c}
    return build_travel_graph([seg_ab, seg_bc], stations)
```

And the D/X/Y test similarly needs `stations = {"D": d, "X": x, "Y": y}` passed as the second argument to `build_travel_graph`.

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_ilp.py -v`
Expected: 4 passed (same 4 tests as before, now against the new graph).

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: failures only in files not yet updated by this plan (`test_simulated_annealing.py`, `test_committed_window_strategy.py`, and anything importing the old `travel_graph` signature) — confirm the failures are exactly the ones Tasks 3-4 will fix, not something new.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/rolling_ilp.py tests/test_rolling_ilp.py
git commit -m "refactor: rolling_ilp uses shortest_travel_days_any_direction (turn-aware graph)"
```

---

## Task 3: Update `simulated_annealing.py` to the direction-unknown approximation

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/simulated_annealing.py`
- Modify: `tests/test_simulated_annealing.py`

**Interfaces:**
- Consumes: `shortest_travel_days_any_direction` (Task 1).
- Produces: no change to `solve_window_sa`'s public signature.

- [ ] **Step 1: Update the import and all three call sites**

In `simulated_annealing.py`, replace `from .travel_graph import shortest_travel_days` with `from .travel_graph import shortest_travel_days_any_direction`, and update all 3 call sites (in `_evaluate_tour`, `_construct_initial_order`, and `solve_window_sa`'s `reachable` filter) from `shortest_travel_days(graph, ..., ...)` to `shortest_travel_days_any_direction(graph, ..., ...)`.

- [ ] **Step 2: Update the test file's graph construction calls**

`tests/test_simulated_annealing.py` builds graphs via `build_travel_graph([seg])` and `build_travel_graph([seg_ab])` (1-arg). Add a `stations` dict as the second argument in each of the 3 tests, mirroring Task 2 Step 2's pattern (e.g., `test_solve_window_sa_empty_candidates_returns_feasible_empty_plan` needs `stations = {"A": a}`; `test_solve_window_sa_skips_unreachable_candidate_instead_of_failing` needs `stations = {"A": a, "B": b}`; `test_solve_window_sa_prioritizes_already_due_candidate_over_cheaper_route` needs `stations = {"D": d, "X": x, "Y": y}`).

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simulated_annealing.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/simulated_annealing.py tests/test_simulated_annealing.py
git commit -m "refactor: simulated_annealing uses shortest_travel_days_any_direction (turn-aware graph)"
```

---

## Task 4: Rewrite `CommittedWindowStrategy` execution to follow the real shortest path

**Files:**
- Modify: `src/railroad_backend/services/auto_planner_strategies/committed_window.py`
- Modify: `tests/test_committed_window_strategy.py`

**Interfaces:**
- Consumes: `build_travel_graph(segments, stations)`, `shortest_travel_days(graph, state, station)`, `shortest_path_first_step(graph, state, station)`, `PathStep` (Task 1).
- Produces: `CommittedWindowStrategy.decide_next_action`/`_should_replan`/`_next_real_move_toward` behavior changes (greedy nearest-neighbor → exact shortest-path-following), but the class's public contract (constructor, `decide_next_action(sim) -> StepDecision`, the abstract `_solve_window`) is unchanged — `RollingHorizonILPStrategy` and `SimulatedAnnealingStrategy` need no changes at all.

This replaces the "pick the immediately-adjacent option that minimizes distance to target" heuristic (which could enter dead ends) with "compute the real shortest path (turn-aware) and take its first step" (correct by construction).

- [ ] **Step 1: Update existing tests for the new signatures, and add turn-following coverage**

Rewrite `tests/test_committed_window_strategy.py` in full:

```python
"""Tests for CommittedWindowStrategy: the shared hysteresis/commitment layer
that fixes rolling-horizon "nervousness", now backed by a turn-aware
shortest-path-following execution instead of a greedy nearest-neighbor
heuristic that could wander into dead ends requiring an un-modeled turn."""
import json
from pathlib import Path
from typing import List

from railroad_backend.services.auto_planner_strategies.committed_window import (
    CommittedWindowStrategy,
)
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan, WindowStop
from src.simulator import Simulator
from src.utils.network_loader import load_network


def _write_network(path: Path, *, extra_stations=None, extra_segments=None) -> None:
    stations = [
        {"name": "A", "can_turn": False},
        {"name": "B", "can_turn": False},
        {"name": "C", "can_turn": False},
    ] + (extra_stations or [])
    segments = [
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
    ] + (extra_segments or [])
    path.write_text(json.dumps({"name": "Chain", "stations": stations, "segments": segments}), encoding="utf-8")


def _chain_sim(tmp_path: Path, *, both_due: bool = True) -> Simulator:
    network_path = tmp_path / "chain.json"
    _write_network(network_path)
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

    d1 = strategy.decide_next_action(sim)
    sim.move_to(d1.segments, d1.next_station, action=d1.action)
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # B-C still cached and still due -- no new solve
    assert strategy.solve_calls == 1


def test_replans_once_the_cached_plan_is_exhausted(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)
    first_plan = WindowPlan(stops=[WindowStop(station_name="B", segment_name="A-B", arrival_day=1)], feasible=True)
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([first_plan, second_plan])

    d1 = strategy.decide_next_action(sim)
    sim.move_to(d1.segments, d1.next_station, action=d1.action)
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # cache empty -- must replan
    assert strategy.solve_calls == 2


def test_replans_when_a_new_already_due_candidate_appears_outside_the_cached_plan(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)  # only A-B due at first
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

    b_c = next(s for s in sim.segments if s.name == "B-C")
    b_c.load_curva = 10.0  # becomes due *now*, outside the cached plan's candidate set

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 2, "a newly-due candidate outside the cached plan must force a replan"


def test_replans_when_cached_target_becomes_unreachable_from_current_position(tmp_path):
    sim = _chain_sim(tmp_path, both_due=True)
    plan = WindowPlan(
        stops=[WindowStop(station_name="Island", segment_name="ghost-segment", arrival_day=99)],
        feasible=True,
    )
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([plan, second_plan])

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 2, "an unreachable cached target must force a replan instead of flailing forever"


def test_turns_first_when_the_target_requires_a_direction_change(tmp_path):
    """Regression test for the architectural gap found on the real network:
    if reaching the cached target requires a turn, the strategy must turn
    -- not wander among adjacent stations hoping one of them is closer.
    Network: A (can_turn) --Singela-- B --CARREGADO-only(-LP)-- C. Starting
    at A facing B (CARREGADO), B-C is reachable directly. But if the machine
    is in VAZIO at A, reaching C requires turning at A first."""
    network_path = tmp_path / "turn_network.json"
    network_path.write_text(
        json.dumps(
            {
                "name": "TurnNetwork",
                "stations": [
                    {"name": "A", "can_turn": True},
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
                        "name": "B-C-LP", "start": "B", "end": "C", "length_km": 1.0,
                        "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    sim = Simulator(load_network(network_path))
    sim.init_machine(start_station_name="A", facing_station_name="B", start_year=2025)
    assert sim.machine.global_direction == "CARREGADO"
    sim.machine.global_direction = "VAZIO"  # force the direction that needs a turn to reach C
    sim.machine.facing = "Vazio"

    plan = WindowPlan(stops=[WindowStop(station_name="C", segment_name="B-C-LP", arrival_day=2)], feasible=True)
    strategy = _RecordingStrategy([plan])

    decision = strategy.decide_next_action(sim)
    assert decision.kind == "turn", f"expected a turn at A first, got {decision.kind}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_committed_window_strategy.py -v`
Expected: FAIL — `committed_window.py` still calls the old `build_travel_graph(sim.segments)` (1-arg) and the old greedy `_next_real_move_toward`; the new turn test in particular has no way to pass currently.

- [ ] **Step 3: Rewrite `committed_window.py`**

```python
# src/railroad_backend/services/auto_planner_strategies/committed_window.py
"""Shared "solve once, commit until invalidated" execution layer.

Rolling-horizon strategies that resolve a full planning model on every
single real step suffer from "nervousness" -- a documented phenomenon in
rolling-horizon/MRP scheduling (Jensen 1993, "Nervousness and Reorder
Policies in Rolling Horizon Environments"; Heisig 2002, "Nervousness in
Material Requirements Planning Systems"; Kimms 1997, "Rolling Planning
Horizon") where near-tied solutions flip between consecutive replans.

This base class caches the resolved `WindowPlan` and keeps executing it
until either the plan is exhausted, or a candidate that's due *right now*
turns up outside the set the cached plan was built from, or the cached
target becomes unreachable from wherever the machine actually is.

Real execution follows the exact shortest path (turn-aware, via
`shortest_path_first_step`) instead of picking whichever immediately
adjacent option looks closest -- the greedy nearest-neighbor heuristic
could wander into a pocket the target wasn't reachable from without an
un-modeled turn, and then had no signal left to prefer forward progress
over backtracking (confirmed on the real network as an indefinite
2-station oscillation -- 2026-08-11/12 diagnostic).
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, List, Optional, Set

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import DueCandidate, project_due_candidates
from .rolling_ilp import WindowPlan
from .travel_graph import State, build_travel_graph, shortest_path_first_step, shortest_travel_days

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
        if station is None or sim.machine is None:
            return self._fallback.decide_next_action(sim)
        current_state: State = (station.name, sim.machine.global_direction)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments, sim.stations)

        if self._should_replan(candidates, graph, current_state):
            plan = self._solve_window(candidates, graph, station.name)
            self._cached_plan = plan
            self._cached_candidate_names = {c.segment_name for c in candidates}

        plan = self._cached_plan
        if plan is None or not plan.feasible or not plan.stops:
            self._cached_plan = None
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        target_segment_name = plan.stops[0].segment_name
        decision = self._next_real_move_toward(sim, graph, current_state, target_station)
        if decision.kind == "move" and any(seg.name == target_segment_name for seg in (decision.segments or ())):
            plan.stops.pop(0)
        return decision

    def _should_replan(self, candidates: List[DueCandidate], graph: "nx.DiGraph", current_state: State) -> bool:
        if self._cached_plan is None or not self._cached_plan.stops:
            return True
        newly_due = {c.segment_name for c in candidates if c.days_until_due == 0}
        if not newly_due.issubset(self._cached_candidate_names):
            return True
        target_station = self._cached_plan.stops[0].station_name
        if shortest_travel_days(graph, current_state, target_station) is None:
            return True
        return False

    def _next_real_move_toward(
        self, sim: "Simulator", graph: "nx.DiGraph", current_state: State, target_station: str
    ) -> StepDecision:
        step = shortest_path_first_step(graph, current_state, target_station)
        if step is None:
            return self._fallback.decide_next_action(sim)
        if step.kind == "turn":
            return StepDecision(kind="turn")

        options = sim.get_possible_moves() or sim.get_all_moves_any_direction()
        match = next((opt for opt in options if opt[1].name == step.next_station), None)
        if match is None:
            return self._fallback.decide_next_action(sim)
        segments, next_station = match
        if needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["CommittedWindowStrategy"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_committed_window_strategy.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions (this also exercises `test_rolling_horizon_ilp_strategy.py` and `test_simulated_annealing_strategy.py`, which go through `CommittedWindowStrategy` but don't reference `travel_graph` directly — confirm they still pass unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/committed_window.py tests/test_committed_window_strategy.py
git commit -m "fix: CommittedWindowStrategy follows the real turn-aware shortest path instead of nearest-neighbor"
```

---

## Task 5: Real-network validation — confirm the oscillation is gone

**Files:** none (validation-only task, no code changes).

- [ ] **Step 1: Re-run the step-by-step diagnostic against the real network**

Use the same diagnostic approach from the 2026-08-11 investigation: initialize a `rolling_ilp` strategy against `data/networks/network_20251223_115340.json` / `data/mtbt_schedule.csv` (ZTO start, ZCZ facing, 2026-2027, 2º KLD), and step it 40 times, printing each decision (station, action, segment). A one-off script is fine (not part of the pytest suite) — write it to the scratchpad directory, not the repo, since it's throwaway.

Expected: no repeating 2-station back-and-forth pattern (the ZQX↔ZIQ loop from the prior diagnostic must not reappear); the machine should reach and maintain segments that were previously stuck at ~8x their MTBT threshold (`ZKE-ZBL-C` and neighbors).

- [ ] **Step 2: If the oscillation is gone, proceed to Task 6. If it persists**

Stop. Do not attempt further ad-hoc fixes in this task — per the systematic-debugging pattern already applied twice in this line of work, a persisting identical symptom after a scoped architectural fix means something about the fix's assumptions is wrong, not that one more patch is needed. Report the concrete new evidence to Bruno before touching code again.

---

## Task 6: Run the multi-horizon study for real and review with Bruno

**Files:**
- Create (by running the script): `docs/2026-08-11-auto-planner-algorithm-study.md`
- Modify: `SecondBrain/projetos/simulador-esmerilhamento/decisoes.md` (outside this repo)

- [ ] **Step 1: Run the study script**

Run: `.venv\Scripts\python.exe scripts\compare_auto_strategies.py` (already written in the prior round — no changes needed, it only calls the public `run_auto_plan_from_args` interface, which didn't change). Budget significant wall-clock time (the prior round's sanity check measured ~1.2s/step for the ILP strategy at 400 steps; run in the background with a generous timeout).

- [ ] **Step 2: Review the report together with Bruno**

Read `docs/2026-08-11-auto-planner-algorithm-study.md` with Bruno. This is the actual deliverable he asked for at the start of this line of work ("testar de fato os algoritmos, olhar os planos gerados e comportamentos, pra avaliar se faz sentido") — a human-in-the-loop step, not something to resolve unilaterally in code.

- [ ] **Step 3: Record the outcome**

Append an entry to `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` with the real headline numbers, confirmation that the turn-aware fix resolved the oscillation, and whatever Bruno decides about next steps (weight recalibration, a UI decision, tracking direction inside the CP-SAT/SA models explicitly, or something else). Do not guess at his preference.

- [ ] **Step 4: Commit the generated report**

```bash
git add docs/2026-08-11-auto-planner-algorithm-study.md
git commit -m "docs: Auto Planner algorithm study results (turn-aware graph) - Greedy vs ILP+hysteresis vs Simulated Annealing"
```

---

## Post-plan note for the implementer

This plan does not track direction as a decision variable inside the CP-SAT/SA models themselves (`shortest_travel_days_any_direction` remains an approximation for ranking candidates within a window). That's explicitly out of scope per the spec — only attempt it if Task 6's review with Bruno concludes the approximation is materially hurting plan quality, and only after discussing it with him first.
