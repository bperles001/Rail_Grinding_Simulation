# Auto Planner Strategy Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Auto Planner's decision logic out of its execution loop into a pluggable `AutoPlanStrategy` interface, migrate the existing heuristic to `GreedyUrgencyStrategy` (behavior-preserving), and add a new `RollingHorizonILPStrategy` (OR-Tools CP-SAT) that both can be selected and compared from the UI.

**Architecture:** `run_auto_plan()` keeps its existing per-step loop but now asks a `strategy.decide_next_action(sim)` object what to do next, then executes that decision through the real `Simulator` (`move_to`/`wait_days`/`flip_global_direction`) exactly as it does today. `GreedyUrgencyStrategy` is a straight code move of today's logic. `RollingHorizonILPStrategy` adds a planning layer on top: it builds a travel-time graph from the network, projects which segments will hit their MTBT threshold inside a rolling window, solves a CP-SAT model for the best visit order inside that window, executes only the first action of the plan, and re-solves from scratch on the next call. If the solver can't produce a feasible plan in its time budget, it falls back to `GreedyUrgencyStrategy` for that one step.

**Tech Stack:** Python 3.10+, existing `Simulator`/`Segment`/`Station` domain (`src/simulator/core.py`, `src/models/__init__.py`), `networkx>=3.1` (already a dependency), new dependency `ortools` (CP-SAT solver), `pytest` for TDD, Streamlit for the UI (`streamlit_app.py`, `src/railroad_frontend/views/auto_simulation.py`, `src/railroad_frontend/views/comparison.py`).

## Global Constraints

- Repo: `E:\Projetos\Simulador de Esmerilhamento\railroad-maintenance-simulator`. Work directly on `master` (established pattern in this repo — no feature branches), commit after every task.
- `AutoPlanConfig.strategy` defaults to `"greedy"` — every existing caller of `run_auto_plan`/`run_auto_plan_from_args`/`AutoPlanConfig` that doesn't pass `strategy` must keep behaving exactly as before. This is the hard requirement behind Tasks 3-4's regression tests.
- Maintenance actions are never fractioned mid-execution: any CP-SAT model must treat a visit (travel + maintenance) as one atomic block, never split across two plan steps.
- New weight/window parameters must be runtime-configurable (UI sliders / function arguments), never hardcoded constants baked into the solver.
- Run `python -m pytest` (full suite) after every task, not just the new test — this repo's pattern is zero regressions per commit.
- Python import style already used in this codebase mixes `from src.models import ...` and `from ..domain...` relative imports depending on the file's location under `src/`; match whichever style the file you're editing already uses.

---

## Task 1: Add OR-Tools dependency

**Files:**
- Modify: `pyproject.toml` (dependencies list, both `[project].dependencies` and nothing else)
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `ortools` importable as `from ortools.sat.python import cp_model` for every later task.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, under `[project] dependencies = [...]`, add `"ortools>=9.10",` (after `"networkx>=3.1",`).

In `requirements.txt`, add a new line: `ortools>=9.10`.

- [ ] **Step 2: Install into the project's venv**

Run: `.venv\Scripts\python.exe -m pip install "ortools>=9.10"` (Windows venv path already used by this repo per `decisoes.md` — "processo Streamlit relançado limpo pelo `.venv` do projeto").

- [ ] **Step 3: Verify the import works**

Run: `.venv\Scripts\python.exe -c "from ortools.sat.python import cp_model; print(cp_model.CpModel())"`
Expected: prints a `CpModel` object repr, no `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "build: add ortools dependency for rolling-horizon ILP strategy"
```

---

## Task 2: `StepDecision` type and `AutoPlanStrategy` interface

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/__init__.py`
- Create: `src/railroad_backend/services/auto_planner_strategies/base.py`
- Test: `tests/test_auto_planner_strategies.py`

**Interfaces:**
- Produces:
  - `StepDecision` — a frozen dataclass with fields `kind: str` (one of `"move"`, `"wait"`, `"turn"`, `"none"`), `segments: Optional[Tuple[Segment, ...]] = None`, `next_station: Optional[Station] = None`, `action: Optional[str] = None` (one of `models.ACTION_MAINTAIN` / `ACTION_MAINTAIN_CURVES` / `ACTION_MOVE`), `wait_days: Optional[int] = None`.
  - `AutoPlanStrategy` — an abstract base class (`abc.ABC`) with one abstract method: `decide_next_action(self, sim: "Simulator") -> StepDecision`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_planner_strategies.py
"""Tests for the pluggable Auto Planner strategy interface."""
import pytest

from railroad_backend.services.auto_planner_strategies.base import AutoPlanStrategy, StepDecision


def test_step_decision_move_holds_required_fields():
    decision = StepDecision(kind="move", segments=("seg-placeholder",), next_station="station-placeholder", action="maintain")
    assert decision.kind == "move"
    assert decision.action == "maintain"


def test_step_decision_wait_holds_days():
    decision = StepDecision(kind="wait", wait_days=5)
    assert decision.kind == "wait"
    assert decision.wait_days == 5


def test_auto_plan_strategy_is_abstract():
    with pytest.raises(TypeError):
        AutoPlanStrategy()  # abstract method not implemented
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_auto_planner_strategies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'railroad_backend.services.auto_planner_strategies'`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/__init__.py
"""Pluggable decision strategies for the Auto Planner."""
```

```python
# src/railroad_backend/services/auto_planner_strategies/base.py
"""Strategy interface separating Auto Planner decision-making from execution."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from src.models import Segment, Station
    from ...domain.simulator import Simulator


@dataclass(frozen=True)
class StepDecision:
    """One decision for a single Auto Planner step.

    `kind` is one of:
      - "move": travel across `segments` to `next_station`, performing
        `action` (may be `ACTION_MOVE` for a plain move with no maintenance).
      - "wait": stay in place for `wait_days` days.
      - "turn": flip global direction at the current (turn-capable) station.
      - "none": no valid action exists; the planner should stop.
    """

    kind: str
    segments: Optional[Tuple["Segment", ...]] = None
    next_station: Optional["Station"] = None
    action: Optional[str] = None
    wait_days: Optional[int] = None


class AutoPlanStrategy(abc.ABC):
    """Decides the next action for an Auto Planner run, given simulator state."""

    @abc.abstractmethod
    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        """Return the next decision for the current simulator state."""
        raise NotImplementedError


__all__ = ["StepDecision", "AutoPlanStrategy"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_auto_planner_strategies.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies tests/test_auto_planner_strategies.py
git commit -m "feat: add StepDecision/AutoPlanStrategy interface for Auto Planner"
```

---

## Task 3: `GreedyUrgencyStrategy` — migrate existing logic

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/greedy.py`
- Modify: `tests/test_auto_planner_strategies.py`

**Interfaces:**
- Consumes: `StepDecision`, `AutoPlanStrategy` from Task 2. `Simulator.get_possible_moves()`, `Simulator.get_all_moves_any_direction()`, `Simulator.current_station.can_turn`, `Simulator.daily_map`, `Simulator.simulation_date`, `Segment.load_curva/load_tangente/mtbt_threshold_curva/mtbt_threshold_tangente/name`.
- Produces: `GreedyUrgencyStrategy` — a concrete `AutoPlanStrategy`. `class GreedyUrgencyStrategy(AutoPlanStrategy): def decide_next_action(self, sim) -> StepDecision`.

This is a pure code move: `_needs_maintenance`, `_component_due`, `_maintenance_action_for`, `_segments_already_due`, `_days_until_next_threshold`, `_move_priority` and the body of `_perform_next_step` (`src/railroad_backend/services/auto_planner.py:131-295`) all move here, unchanged in logic, only restructured to build and return a `StepDecision` instead of calling `sim.move_to`/`sim.wait_days` directly.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_auto_planner_strategies.py
from datetime import datetime
from pathlib import Path

from railroad_backend.services.auto_planner_strategies.greedy import GreedyUrgencyStrategy
from railroad_backend.services.auto_planner import _init_simulation, AutoPlanConfig


def _small_config(tmp_path: Path) -> AutoPlanConfig:
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


def test_greedy_strategy_returns_a_decision(tmp_path):
    sim = _init_simulation(_small_config(tmp_path))
    strategy = GreedyUrgencyStrategy()
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}


def test_greedy_strategy_prioritizes_due_segment_over_moving(tmp_path):
    sim = _init_simulation(_small_config(tmp_path))
    # Force the segment leaving the start station to already be due.
    due_segment = next(s for s in sim.segments if s.name == "TRO-TMI")
    due_segment.mtbt_threshold_curva = 1.0
    due_segment.load_curva = 5.0
    due_segment.mtbt_threshold_tangente = 1.0
    due_segment.load_tangente = 5.0
    strategy = GreedyUrgencyStrategy()
    decision = strategy.decide_next_action(sim)
    assert decision.kind == "move"
    assert decision.action in {"maintain", "maintain_curves"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_auto_planner_strategies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '...greedy'`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/greedy.py
"""Greedy urgency-first Auto Planner strategy (the pre-existing default heuristic)."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Dict, Tuple

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


def component_due(seg, component: str) -> bool:
    """True if a single component (curva or tangente) reached its threshold."""
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    load = getattr(seg, f"load_{component}", 0.0) or 0.0
    if threshold is None:
        return False
    try:
        return float(load) >= float(threshold)
    except (TypeError, ValueError):  # pragma: no cover
        return False


def needs_maintenance(segments) -> bool:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    return any(component_due(seg, "curva") or component_due(seg, "tangente") for seg in seq)


def maintenance_action_for(segments) -> str:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    if any(component_due(seg, "tangente") for seg in seq):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES


def segments_already_due(sim: "Simulator") -> bool:
    return any(needs_maintenance(seg) for seg in sim.segments)


def days_until_next_threshold(sim: "Simulator", *, scan_limit_days: int = 180) -> int:
    if not sim.daily_map or not sim.simulation_date:
        return 0
    projected: Dict[str, float] = {}
    thresholds: Dict[str, float] = {}
    component_seg_name: Dict[str, str] = {}
    for seg in sim.segments:
        for component, threshold, load in (
            (f"{seg.name}::curva", seg.mtbt_threshold_curva, seg.load_curva),
            (f"{seg.name}::tangente", seg.mtbt_threshold_tangente, seg.load_tangente),
        ):
            if threshold in (None, 0):
                continue
            thresholds[component] = float(threshold)
            projected[component] = float(load or 0.0)
            component_seg_name[component] = seg.name
    if not thresholds:
        return 0
    if segments_already_due(sim):
        return 0
    cached_daily_vals = {
        component: sim.daily_map.get(component_seg_name[component]) or {}
        for component in thresholds
    }
    current = sim.simulation_date
    for offset in range(1, scan_limit_days + 1):
        date_str = (current + timedelta(days=offset - 1)).strftime("%Y-%m-%d")
        progressed = False
        for component, threshold in thresholds.items():
            daily_values = cached_daily_vals[component]
            increment = daily_values.get(date_str)
            if increment:
                projected[component] = projected.get(component, 0.0) + float(increment)
                progressed = True
            if projected.get(component, 0.0) >= threshold:
                return offset
        if not progressed:
            if not any(daily_vals.get(date_str) for daily_vals in cached_daily_vals.values()):
                break
    return 0


def _move_priority(pair) -> Tuple[int, float, str]:
    segments, _ = pair
    urgent = 0 if needs_maintenance(segments) else 1
    load = max(
        max(
            float(getattr(seg, "load_curva", 0.0) or 0.0),
            float(getattr(seg, "load_tangente", 0.0) or 0.0),
        )
        for seg in segments
    )
    name = "+".join(seg.name for seg in segments)
    return (urgent, -load, name)


class GreedyUrgencyStrategy(AutoPlanStrategy):
    """Same heuristic the Auto Planner has always used: move to the most
    urgent (highest-load, already-due) segment; if nothing is due, wait
    until the next threshold is projected to hit."""

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        if segments_already_due(sim):
            options = sim.get_possible_moves()
            if not options:
                if sim.current_station and sim.current_station.can_turn:
                    return StepDecision(kind="turn")
                options = sim.get_all_moves_any_direction()
                if not options:
                    return StepDecision(kind="none")
            segments, next_station = sorted(options, key=_move_priority)[0]
            action = maintenance_action_for(segments) if needs_maintenance(segments) else ACTION_MOVE
            return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)

        wait_days = days_until_next_threshold(sim)
        if wait_days <= 0:
            if sim.daily_map:
                wait_days = 1
            else:
                return StepDecision(kind="none")
        return StepDecision(kind="wait", wait_days=wait_days)


__all__ = ["GreedyUrgencyStrategy"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_auto_planner_strategies.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/greedy.py tests/test_auto_planner_strategies.py
git commit -m "feat: migrate Auto Planner greedy heuristic into GreedyUrgencyStrategy"
```

---

## Task 4: Wire `run_auto_plan` through the strategy interface

**Files:**
- Modify: `src/railroad_backend/services/auto_planner.py`

**Interfaces:**
- Consumes: `AutoPlanStrategy`, `GreedyUrgencyStrategy`, `StepDecision` from Tasks 2-3.
- Produces: `AutoPlanConfig.strategy: str = "greedy"` (new field, defaults preserve old behavior). `AutoPlanResult.strategy_name: str` (new field). `run_auto_plan(config)` unchanged signature/return type.

This task removes the now-duplicated `_needs_maintenance`/`_component_due`/`_maintenance_action_for`/`_segments_already_due`/`_days_until_next_threshold`/`_move_priority`/`_perform_next_step` from `auto_planner.py` (they now live in `greedy.py`) and replaces `_perform_next_step(sim)` with a strategy-driven `_execute_decision(sim, decision) -> bool`.

- [ ] **Step 1: Confirm the regression baseline passes before touching anything**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py tests/test_edge_cases.py tests/test_basic.py -v -k auto`
Expected: all currently-passing auto-related tests pass (baseline before refactor).

- [ ] **Step 2: Replace the decision logic in `auto_planner.py`**

Delete lines 131-295 of `src/railroad_backend/services/auto_planner.py` (`_component_due` through `_perform_next_step`, inclusive — everything between `_apply_initial_loads`'s end and the `AutoPlanResult` dataclass). Replace the `AutoPlanConfig` dataclass's field list to add `strategy: str = "greedy"` right after `network_source`, and add this near the top of the file (after the existing imports):

```python
from .auto_planner_strategies.base import AutoPlanStrategy, StepDecision
from .auto_planner_strategies.greedy import GreedyUrgencyStrategy

STRATEGY_REGISTRY: Dict[str, "type[AutoPlanStrategy]"] = {
    "greedy": GreedyUrgencyStrategy,
}


def _resolve_strategy(name: str) -> AutoPlanStrategy:
    strategy_cls = STRATEGY_REGISTRY.get(name)
    if strategy_cls is None:
        raise ValueError(f"Unknown Auto Planner strategy: {name!r}. Known: {sorted(STRATEGY_REGISTRY)}")
    return strategy_cls()


def _execute_decision(sim: Simulator, decision: StepDecision) -> bool:
    """Execute a StepDecision against the real simulator. Returns True if progress was made."""
    if decision.kind == "move":
        sim.move_to(decision.segments, decision.next_station, action=decision.action)
        return True
    if decision.kind == "wait":
        return bool(sim.wait_days(decision.wait_days))
    if decision.kind == "turn":
        return sim.flip_global_direction()
    return False
```

Then replace the body of `run_auto_plan`:

```python
def run_auto_plan(config: AutoPlanConfig) -> AutoPlanResult:
    sim = _init_simulation(config)
    strategy = _resolve_strategy(config.strategy)
    limit_date = datetime(config.end_year, 12, 31)
    stop_reason = "steps_limit"
    for _ in range(config.steps):
        decision = strategy.decide_next_action(sim)
        progressed = _execute_decision(sim, decision)
        if not progressed:
            stop_reason = "stalled"
            break
        if sim.simulation_date and sim.simulation_date.date() > limit_date.date():
            stop_reason = "year_limit"
            break
    else:
        stop_reason = "steps_limit"
    stop_details_obj: Dict[str, object] = {
        "limit_date": limit_date.date().isoformat(),
        "steps_requested": str(config.steps),
        "steps_completed": str(len(sim.steps)),
    }
    sim.stop_reason = stop_reason
    sim.stop_details = stop_details_obj
    stop_details_for_result: Dict[str, str] = dict(stop_details_obj)  # type: ignore[arg-type]
    return AutoPlanResult(
        simulator=sim,
        stop_reason=stop_reason,
        stop_details=stop_details_for_result,
        strategy_name=config.strategy,
    )
```

Add `strategy_name: str = "greedy"` to the `AutoPlanResult` dataclass fields, and add `strategy: str = "greedy"` and `strategy: str = "greedy"` keyword args to `run_auto_plan_from_args` and pass it through to `AutoPlanConfig(...)`.

- [ ] **Step 3: Run the regression baseline again**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py tests/test_edge_cases.py tests/test_basic.py tests/test_auto_planner_strategies.py -v`
Expected: same pass count as Step 1, plus the new strategy tests, zero failures, zero behavior change.

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass (no import errors from the deleted functions — grep for any other file importing `_perform_next_step`/`_move_priority`/`_needs_maintenance` etc. from `auto_planner` before finishing this step; there should be none outside `auto_planner.py` itself, but confirm with `grep -rn "_perform_next_step\|_move_priority\|_needs_maintenance" --include=*.py .` from the repo root and fix any stragglers).

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner.py
git commit -m "refactor: run_auto_plan delegates decisions to AutoPlanStrategy (behavior-preserving)"
```

---

## Task 5: Travel-time graph helper

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/travel_graph.py`
- Test: `tests/test_travel_graph.py`

**Interfaces:**
- Consumes: `Simulator.segments` (list of `Segment`, each with `start_station.name`, `end_station.name`, `allowed_movements`, `move_time_days`).
- Produces: `build_travel_graph(segments: Sequence[Segment]) -> networkx.DiGraph` (node = station name, edge weight `"days"` = `move_time_days`, one directed edge per entry in `segment.allowed_movements`). `shortest_travel_days(graph, from_station: str, to_station: str) -> Optional[int]` (returns `None` if unreachable).

Known simplification, to be stated as a comment in the module docstring: this graph ignores the CARREGADO/VAZIO facing restriction that `Simulator.get_possible_moves()` enforces at execution time, and ignores turn-station mechanics — it is only used by `RollingHorizonILPStrategy` to *rank* candidates inside a planning window, never to execute a multi-hop path directly. The real next single step is always re-validated against `sim.get_possible_moves()`/`sim.flip_global_direction()` before execution, so an optimistic distance estimate here cannot produce an invalid real move — it can only make the planner's window-ranking imperfect, which is an acceptable tradeoff documented for a future revisit if Greedy-vs-ILP comparison shows it matters.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_travel_graph.py
"""Tests for the Auto Planner rolling-horizon travel-time graph helper."""
from src.models import Segment, Station
from railroad_backend.services.auto_planner_strategies.travel_graph import (
    build_travel_graph,
    shortest_travel_days,
)


def _linear_segments():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=2)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=3)
    return [seg_ab, seg_bc]


def test_shortest_travel_days_single_hop():
    graph = build_travel_graph(_linear_segments())
    assert shortest_travel_days(graph, "A", "B") == 2


def test_shortest_travel_days_multi_hop_sums_weights():
    graph = build_travel_graph(_linear_segments())
    assert shortest_travel_days(graph, "A", "C") == 5


def test_shortest_travel_days_unreachable_returns_none():
    graph = build_travel_graph(_linear_segments())
    graph.add_node("Z")
    assert shortest_travel_days(graph, "A", "Z") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_travel_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/travel_graph.py
"""Travel-time graph for ranking candidates inside a rolling-horizon plan.

This graph is a simplification: it ignores the CARREGADO/VAZIO facing
restriction that `Simulator.get_possible_moves()` enforces at execution
time, and ignores turn-station mechanics. It is only used to rank
candidates inside `RollingHorizonILPStrategy`'s planning window — the real
next single step is always re-validated against `sim.get_possible_moves()`
before execution, so an optimistic distance estimate here cannot produce
an invalid real move.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

import networkx as nx

if TYPE_CHECKING:
    from src.models import Segment


def build_travel_graph(segments: Sequence["Segment"]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for segment in segments:
        weight = max(1, int(segment.move_time_days))
        for src, dst in segment.allowed_movements:
            graph.add_edge(src, dst, days=weight)
    return graph


def shortest_travel_days(graph: nx.DiGraph, from_station: str, to_station: str) -> Optional[int]:
    if from_station == to_station:
        return 0
    if from_station not in graph or to_station not in graph:
        return None
    try:
        return nx.shortest_path_length(graph, from_station, to_station, weight="days")
    except nx.NetworkXNoPath:
        return None


__all__ = ["build_travel_graph", "shortest_travel_days"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_travel_graph.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/travel_graph.py tests/test_travel_graph.py
git commit -m "feat: add travel-time graph helper for rolling-horizon planning"
```

---

## Task 6: Horizon projection helper

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/horizon.py`
- Test: `tests/test_horizon.py`

**Interfaces:**
- Consumes: `Simulator.segments`, `Simulator.daily_map`, `Simulator.simulation_date`.
- Produces:
  - `@dataclass(frozen=True) class DueCandidate: segment_name: str; station_name: str; days_until_due: int; service_days: int` (`station_name` is `segment.end_station.name`, the node to travel toward; `service_days` is `segment.maintenance_time_days`).
  - `project_due_candidates(sim: Simulator, horizon_days: int) -> List[DueCandidate]` — one `DueCandidate` per segment that either already needs maintenance (`days_until_due=0`) or is projected to need it within `horizon_days` (reusing the same daily-map scanning approach as `greedy.days_until_next_threshold`, but per-segment instead of network-wide).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_horizon.py
"""Tests for the rolling-horizon due-candidate projection helper."""
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.horizon import project_due_candidates


def _config(tmp_path: Path, csv_data: str) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text(csv_data)
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_already_due_segment_has_zero_days_until_due(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,8.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 1.0
    seg.load_curva = 5.0
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next(c for c in candidates if c.segment_name == "TRO-TMI")
    assert match.days_until_due == 0


def test_segment_outside_horizon_is_excluded(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,0.1\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 1000.0
    seg.mtbt_threshold_tangente = 1000.0
    candidates = project_due_candidates(sim, horizon_days=5)
    assert not any(c.segment_name == "TRO-TMI" for c in candidates)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_horizon.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/horizon.py
"""Projects which segments will need maintenance inside a rolling window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, List

from .greedy import component_due

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


@dataclass(frozen=True)
class DueCandidate:
    segment_name: str
    station_name: str
    days_until_due: int
    service_days: int


def _days_until_component_due(sim: "Simulator", seg, component: str, horizon_days: int) -> "int | None":
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    if not threshold:
        return None
    load = float(getattr(seg, f"load_{component}", 0.0) or 0.0)
    if load >= float(threshold):
        return 0
    if not sim.daily_map or not sim.simulation_date:
        return None
    daily_values = sim.daily_map.get(seg.name) or {}
    projected = load
    current = sim.simulation_date
    for offset in range(1, horizon_days + 1):
        date_str = (current + timedelta(days=offset - 1)).strftime("%Y-%m-%d")
        increment = daily_values.get(date_str)
        if increment:
            projected += float(increment)
        if projected >= float(threshold):
            return offset
    return None


def project_due_candidates(sim: "Simulator", horizon_days: int) -> List[DueCandidate]:
    candidates: List[DueCandidate] = []
    for seg in sim.segments:
        curva_days = _days_until_component_due(sim, seg, "curva", horizon_days)
        tangente_days = _days_until_component_due(sim, seg, "tangente", horizon_days)
        due_days = [d for d in (curva_days, tangente_days) if d is not None]
        if not due_days:
            continue
        candidates.append(
            DueCandidate(
                segment_name=seg.name,
                station_name=seg.end_station.name,
                days_until_due=min(due_days),
                service_days=max(1, int(seg.maintenance_time_days)),
            )
        )
    return candidates


__all__ = ["DueCandidate", "project_due_candidates"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_horizon.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/horizon.py tests/test_horizon.py
git commit -m "feat: add rolling-horizon due-candidate projection helper"
```

---

## Task 7: CP-SAT window solver

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/rolling_ilp.py`
- Test: `tests/test_rolling_ilp.py`

**Interfaces:**
- Consumes: `DueCandidate` (Task 6), `build_travel_graph`/`shortest_travel_days` (Task 5).
- Produces:
  - `@dataclass(frozen=True) class WindowStop: station_name: str; segment_name: str; arrival_day: int` — one visit in the solved plan, in order.
  - `@dataclass(frozen=True) class WindowPlan: stops: List[WindowStop]; feasible: bool` — `feasible=False` when the solver found no solution in its time budget; `stops` is then empty.
  - `solve_window(candidates: List[DueCandidate], graph: nx.DiGraph, start_station: str, *, weight_coverage: float, weight_travel: float, weight_proximity: float, time_limit_s: float = 20.0) -> WindowPlan`

**Model**: nodes are `[depot] + candidates` (depot = `start_station`, index 0). Build a CP-SAT "optional circuit" (`AddCircuit`) over all node pairs: a real arc `(i, j)` for `i != j` when `shortest_travel_days` connects them (cost = travel days from `graph`, plus `candidates[j-1].service_days` folded into the arrival-time constraint, not the arc cost); a self-arc `(i, i)` for every candidate node (never for the depot) representing "this candidate is skipped". Integer `arrival_day[i]` per node, `arrival_day[depot] = 0`, and for every real arc `(i, j)` chosen: `arrival_day[j] >= arrival_day[i] + travel_days(i, j)` (enforced via `OnlyEnforceIf`). To make an *open* path (no need to return to depot) representable as a circuit, every arc back into the depot costs 0 in the objective — only forward arcs into candidate nodes count.

Objective (minimize):
- `weight_coverage * sum(skip_literal[i] for i in candidates)` — cost of not visiting a candidate at all within the window.
- `weight_travel * sum(travel_days(i, j) * arc_literal[i, j] for each real arc chosen)`.
- `weight_proximity * sum(max(0, candidates[i].days_until_due - arrival_day_of(i)) for visited i)` — penalizes servicing far *before* the deadline (the "don't waste cycle life" objective); implemented as an integer slack variable `earliness[i] >= 0` with `earliness[i] >= due_day[i] - arrival_day[i]` and `earliness[i] >= 0`, added to the objective.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rolling_ilp.py
"""Tests for the CP-SAT rolling-horizon window solver."""
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.rolling_ilp import solve_window
from railroad_backend.services.auto_planner_strategies.travel_graph import build_travel_graph
from src.models import Segment, Station


def _three_node_graph():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=1, maintenance_time_days=1)
    return build_travel_graph([seg_ab, seg_bc])


def test_solve_window_visits_both_reachable_candidates_when_cheap():
    graph = _three_node_graph()
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=10, service_days=1),
        DueCandidate(segment_name="B-C", station_name="C", days_until_due=20, service_days=1),
    ]
    plan = solve_window(
        candidates, graph, start_station="A",
        weight_coverage=100.0, weight_travel=1.0, weight_proximity=0.1,
        time_limit_s=5.0,
    )
    assert plan.feasible
    visited_segments = [stop.segment_name for stop in plan.stops]
    assert visited_segments == ["A-B", "B-C"]


def test_solve_window_skips_unreachable_candidate_instead_of_failing():
    graph = _three_node_graph()
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=10, service_days=1),
        DueCandidate(segment_name="ghost", station_name="Nowhere", days_until_due=5, service_days=1),
    ]
    plan = solve_window(
        candidates, graph, start_station="A",
        weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1,
        time_limit_s=5.0,
    )
    assert plan.feasible
    visited_segments = [stop.segment_name for stop in plan.stops]
    assert "A-B" in visited_segments
    assert "ghost" not in visited_segments


def test_solve_window_empty_candidates_returns_feasible_empty_plan():
    graph = _three_node_graph()
    plan = solve_window([], graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1)
    assert plan.feasible
    assert plan.stops == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_ilp.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/rolling_ilp.py
"""CP-SAT solver for a single rolling-horizon planning window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Tuple

from ortools.sat.python import cp_model

from .travel_graph import shortest_travel_days

if TYPE_CHECKING:
    import networkx as nx

    from .horizon import DueCandidate

_BIG_HORIZON = 3650  # upper bound on any arrival day inside a window, in days


@dataclass(frozen=True)
class WindowStop:
    station_name: str
    segment_name: str
    arrival_day: int


@dataclass(frozen=True)
class WindowPlan:
    stops: List[WindowStop]
    feasible: bool


def solve_window(
    candidates: List["DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    *,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
    time_limit_s: float = 20.0,
) -> WindowPlan:
    if not candidates:
        return WindowPlan(stops=[], feasible=True)

    # Node 0 is the depot (current position). Nodes 1..n are candidates.
    # Only keep candidates actually reachable from the depot within the graph.
    reachable: List[Tuple[int, "DueCandidate", int]] = []
    for idx, candidate in enumerate(candidates, start=1):
        travel_days = shortest_travel_days(graph, start_station, candidate.station_name)
        if travel_days is not None:
            reachable.append((idx, candidate, travel_days))
    if not reachable:
        return WindowPlan(stops=[], feasible=True)

    nodes = [0] + [idx for idx, _, _ in reachable]
    by_node: Dict[int, "DueCandidate"] = {idx: candidate for idx, candidate, _ in reachable}
    station_by_node: Dict[int, str] = {0: start_station}
    station_by_node.update({idx: candidate.station_name for idx, candidate, _ in reachable})

    model = cp_model.CpModel()
    arcs: List[Tuple[int, int, "cp_model.IntVar"]] = []
    skip_literal: Dict[int, "cp_model.IntVar"] = {}
    arc_literal: Dict[Tuple[int, int], "cp_model.IntVar"] = {}
    arc_travel_days: Dict[Tuple[int, int], int] = {}

    for i in nodes:
        for j in nodes:
            if i == j:
                if i != 0:
                    lit = model.NewBoolVar(f"skip_{i}")
                    skip_literal[i] = lit
                    arcs.append((i, i, lit))
                continue
            travel = shortest_travel_days(graph, station_by_node[i], station_by_node[j])
            if travel is None:
                continue
            lit = model.NewBoolVar(f"arc_{i}_{j}")
            arc_literal[(i, j)] = lit
            arc_travel_days[(i, j)] = travel
            arcs.append((i, j, lit))

    model.AddCircuit(arcs)

    arrival_day: Dict[int, "cp_model.IntVar"] = {
        node: model.NewIntVar(0, _BIG_HORIZON, f"arrival_{node}") for node in nodes
    }
    model.Add(arrival_day[0] == 0)

    earliness_terms = []
    for (i, j), lit in arc_literal.items():
        travel = arc_travel_days[(i, j)]
        service = by_node[j].service_days if j in by_node else 0
        model.Add(arrival_day[j] >= arrival_day[i] + travel).OnlyEnforceIf(lit)
        if j in by_node:
            due_day = by_node[j].days_until_due
            earliness = model.NewIntVar(0, _BIG_HORIZON, f"earliness_{j}")
            model.Add(earliness >= due_day - arrival_day[j]).OnlyEnforceIf(lit)
            model.Add(earliness >= 0)
            earliness_terms.append(earliness)

    coverage_term = sum(skip_literal.values())
    travel_term = sum(
        arc_travel_days[(i, j)] * lit for (i, j), lit in arc_literal.items() if j != 0
    )
    proximity_term = sum(earliness_terms) if earliness_terms else 0

    scale = 1000  # CP-SAT objective coefficients must be integers
    model.Minimize(
        int(weight_coverage * scale) * coverage_term
        + int(weight_travel * scale) * travel_term
        + int(weight_proximity * scale) * proximity_term
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return WindowPlan(stops=[], feasible=False)

    # Walk the circuit starting at the depot to recover visit order.
    successor: Dict[int, int] = {}
    for (i, j), lit in arc_literal.items():
        if solver.Value(lit):
            successor[i] = j
    stops: List[WindowStop] = []
    current = 0
    visited_nodes = set()
    while current in successor and successor[current] != 0:
        nxt = successor[current]
        if nxt in visited_nodes:  # pragma: no cover - defensive, circuit shouldn't loop early
            break
        visited_nodes.add(nxt)
        candidate = by_node[nxt]
        stops.append(
            WindowStop(
                station_name=station_by_node[nxt],
                segment_name=candidate.segment_name,
                arrival_day=solver.Value(arrival_day[nxt]),
            )
        )
        current = nxt

    return WindowPlan(stops=stops, feasible=True)


__all__ = ["WindowStop", "WindowPlan", "solve_window"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_ilp.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/rolling_ilp.py tests/test_rolling_ilp.py
git commit -m "feat: add CP-SAT rolling-horizon window solver"
```

---

## Task 8: `RollingHorizonILPStrategy` with Greedy fallback

**Files:**
- Create: `src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py`
- Test: `tests/test_rolling_horizon_ilp_strategy.py`

**Interfaces:**
- Consumes: `AutoPlanStrategy`/`StepDecision` (Task 2), `GreedyUrgencyStrategy` (Task 3), `build_travel_graph` (Task 5), `project_due_candidates` (Task 6), `solve_window`/`WindowPlan` (Task 7).
- Produces: `class RollingHorizonILPStrategy(AutoPlanStrategy)`, constructor `__init__(self, *, window_days: int = 60, weight_coverage: float = 10.0, weight_travel: float = 1.0, weight_proximity: float = 0.5, time_limit_s: float = 20.0)`.

Behavior: on every `decide_next_action` call, build the travel graph from `sim.segments`, project candidates via `project_due_candidates(sim, self.window_days)`, solve the window from `sim.current_station.name`. If `plan.feasible` and `plan.stops` is non-empty, translate the **first** stop into a `move` `StepDecision` (segment/station looked up from `sim.segments`/`sim.get_possible_moves()` — see below for how a multi-hop first stop degrades to the correct single real move). If `plan.feasible` but `plan.stops` is empty (nothing due within the window), delegate to `GreedyUrgencyStrategy` for the wait/no-op decision (its "no due segment" branch already does the correct wait-until-next-threshold). If `not plan.feasible`, delegate the whole decision to `GreedyUrgencyStrategy`.

**Multi-hop translation**: the first stop's `station_name` may not be directly adjacent to `sim.current_station` (the travel graph simplification from Task 5 can plan a path several real segments long). `decide_next_action` must only ever return a `StepDecision` that `Simulator.move_to` can execute in one call — so it picks, among `sim.get_possible_moves()`, the option whose segment lies on the shortest real path toward the target station (using `shortest_travel_days` again, choosing the neighbor that minimizes remaining distance to the target). If the target segment itself is directly reachable via `sim.get_possible_moves()`, use the real `maintenance_action_for` (from `greedy.py`) to decide curva/completa for it, matching the same due-component logic Greedy uses; otherwise it's a plain move (`ACTION_MOVE`) toward the target.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rolling_horizon_ilp_strategy.py
"""Tests for RollingHorizonILPStrategy, including its Greedy fallback."""
from pathlib import Path
from unittest.mock import patch

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp import (
    RollingHorizonILPStrategy,
)
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan


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


def test_rolling_ilp_falls_back_to_greedy_when_solver_infeasible(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy()
    with patch(
        "railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp.solve_window",
        return_value=WindowPlan(stops=[], feasible=False),
    ):
        decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}  # same shape Greedy would return


def test_rolling_ilp_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy(time_limit_s=5.0)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_horizon_ilp_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py
"""Rolling-horizon CP-SAT strategy with a Greedy fallback for infeasible windows."""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.models import ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision
from .greedy import GreedyUrgencyStrategy, maintenance_action_for, needs_maintenance
from .horizon import project_due_candidates
from .rolling_ilp import solve_window
from .travel_graph import build_travel_graph, shortest_travel_days

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


class RollingHorizonILPStrategy(AutoPlanStrategy):
    """Plans a rolling window with CP-SAT; executes only the first action of
    the best plan found, and replans from scratch on the next call."""

    def __init__(
        self,
        *,
        window_days: int = 60,
        weight_coverage: float = 10.0,
        weight_travel: float = 1.0,
        weight_proximity: float = 0.5,
        time_limit_s: float = 20.0,
    ) -> None:
        self.window_days = window_days
        self.weight_coverage = weight_coverage
        self.weight_travel = weight_travel
        self.weight_proximity = weight_proximity
        self.time_limit_s = time_limit_s
        self._fallback = GreedyUrgencyStrategy()

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        station = sim.current_station
        if station is None:
            return self._fallback.decide_next_action(sim)

        candidates = project_due_candidates(sim, self.window_days)
        graph = build_travel_graph(sim.segments)
        plan = solve_window(
            candidates,
            graph,
            start_station=station.name,
            weight_coverage=self.weight_coverage,
            weight_travel=self.weight_travel,
            weight_proximity=self.weight_proximity,
            time_limit_s=self.time_limit_s,
        )

        if not plan.feasible or not plan.stops:
            return self._fallback.decide_next_action(sim)

        target_station = plan.stops[0].station_name
        target_segment_name = plan.stops[0].segment_name
        return self._next_real_move_toward(sim, graph, target_station, target_segment_name)

    def _next_real_move_toward(
        self, sim: "Simulator", graph, target_station: str, target_segment_name: str
    ) -> StepDecision:
        options = sim.get_possible_moves()
        if not options:
            return self._fallback.decide_next_action(sim)

        def remaining_distance(option) -> float:
            segments, next_station = option
            distance = shortest_travel_days(graph, next_station.name, target_station)
            return float("inf") if distance is None else distance

        segments, next_station = min(options, key=remaining_distance)
        on_target_segment = any(seg.name == target_segment_name for seg in segments)
        if on_target_segment and needs_maintenance(segments):
            action = maintenance_action_for(segments)
        else:
            action = ACTION_MOVE
        return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)


__all__ = ["RollingHorizonILPStrategy"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rolling_horizon_ilp_strategy.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner_strategies/rolling_horizon_ilp.py tests/test_rolling_horizon_ilp_strategy.py
git commit -m "feat: add RollingHorizonILPStrategy with Greedy fallback"
```

---

## Task 9: Register the strategy and expose parameters through `AutoPlanConfig`

**Files:**
- Modify: `src/railroad_backend/services/auto_planner.py`
- Modify: `tests/test_integration.py` (add one new test, do not touch existing ones)

**Interfaces:**
- Consumes: `RollingHorizonILPStrategy` (Task 8).
- Produces: `AutoPlanConfig` gains optional fields `ilp_window_days: int = 60`, `ilp_weight_coverage: float = 10.0`, `ilp_weight_travel: float = 1.0`, `ilp_weight_proximity: float = 0.5`, `ilp_time_limit_s: float = 20.0` (all ignored unless `strategy == "rolling_ilp"`). `run_auto_plan_from_args` gains the same keyword arguments, passed through.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_integration.py, inside the AUTO PLANNING WORKFLOW TESTS section
def test_auto_plan_rolling_ilp_strategy_runs_end_to_end(tmp_path):
    """Rolling-horizon ILP strategy produces a valid result on a tiny network."""
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
        strategy="rolling_ilp",
        ilp_time_limit_s=5.0,
    )
    result = run_auto_plan(config)
    assert result.strategy_name == "rolling_ilp"
    assert isinstance(result, AutoPlanResult)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k rolling_ilp -v`
Expected: FAIL with `TypeError: AutoPlanConfig.__init__() got an unexpected keyword argument 'strategy'` (or `ValueError: Unknown Auto Planner strategy` if `strategy` already exists from Task 4 but `"rolling_ilp"` isn't registered yet).

- [ ] **Step 3: Wire it up**

In `src/railroad_backend/services/auto_planner.py`:
1. Add the import: `from .auto_planner_strategies.rolling_horizon_ilp import RollingHorizonILPStrategy`.
2. Add `"rolling_ilp": RollingHorizonILPStrategy` to `STRATEGY_REGISTRY`.
3. In `AutoPlanConfig`, add the 5 new fields listed above (with defaults, right after `strategy: str = "greedy"`).
4. In `_resolve_strategy`, when `name == "rolling_ilp"`, construct it with the config's ILP fields instead of `strategy_cls()`:

```python
def _resolve_strategy(config: "AutoPlanConfig") -> AutoPlanStrategy:
    strategy_cls = STRATEGY_REGISTRY.get(config.strategy)
    if strategy_cls is None:
        raise ValueError(f"Unknown Auto Planner strategy: {config.strategy!r}. Known: {sorted(STRATEGY_REGISTRY)}")
    if config.strategy == "rolling_ilp":
        return RollingHorizonILPStrategy(
            window_days=config.ilp_window_days,
            weight_coverage=config.ilp_weight_coverage,
            weight_travel=config.ilp_weight_travel,
            weight_proximity=config.ilp_weight_proximity,
            time_limit_s=config.ilp_time_limit_s,
        )
    return strategy_cls()
```

(This changes `_resolve_strategy`'s signature from `(name: str)` to `(config: AutoPlanConfig)` — update its one call site in `run_auto_plan` from `_resolve_strategy(config.strategy)` to `_resolve_strategy(config)`.)

5. Add the same 5 keyword arguments to `run_auto_plan_from_args`, passed through to `AutoPlanConfig(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -v`
Expected: all pass, including the new `test_auto_plan_rolling_ilp_strategy_runs_end_to_end`.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all tests pass, zero regressions.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/services/auto_planner.py tests/test_integration.py
git commit -m "feat: register RollingHorizonILPStrategy and expose its parameters on AutoPlanConfig"
```

---

## Task 10: UI — strategy selector and weight sliders

**Files:**
- Modify: `src/railroad_frontend/views/auto_simulation.py`
- Modify: `streamlit_app.py` (the `run_auto_plan` wrapper around line 251, per the earlier grep of this file)

**Interfaces:**
- Consumes: `AutoPlanConfig`'s new fields (Task 9), `run_auto_plan_from_args`'s new keyword arguments (Task 9).
- Produces: no new Python interfaces — this task only changes what the Streamlit form collects and passes through. `config` dict gains keys `"strategy"`, and when `strategy == "rolling_ilp"`: `"ilp_window_days"`, `"ilp_weight_coverage"`, `"ilp_weight_travel"`, `"ilp_weight_proximity"`.

This task has no automated test (Streamlit UI) — verify manually per the steps below, following this repo's established pattern of relaunching the app clean and checking in the browser (see `decisoes.md` entries from 2026-08-10/11 for the exact relaunch procedure: kill any stray `uv`-managed process, relaunch via `.venv\Scripts\python.exe run_streamlit.py`).

- [ ] **Step 1: Add the strategy selector and conditional weight sliders to the form**

In `src/railroad_frontend/views/auto_simulation.py`, inside `render_auto_simulation_page`, right after the existing `second_kld = ...` checkbox line (around line 148) and before the `form_submitted = ...` line, add:

```python
            st.markdown("---")
            st.markdown("**Strategy**")
            strategy_choices = {"Greedy (atual)": "greedy", "Rolling-horizon ILP": "rolling_ilp"}
            strategy_default_label = next(
                (label for label, value in strategy_choices.items() if value == config.get("strategy", "greedy")),
                "Greedy (atual)",
            )
            strategy_label = st.selectbox(
                "Auto planning strategy",
                list(strategy_choices.keys()),
                index=list(strategy_choices.keys()).index(strategy_default_label),
            )
            strategy = strategy_choices[strategy_label]

            ilp_window_days = int(config.get("ilp_window_days", 60))
            ilp_weight_coverage = float(config.get("ilp_weight_coverage", 10.0))
            ilp_weight_travel = float(config.get("ilp_weight_travel", 1.0))
            ilp_weight_proximity = float(config.get("ilp_weight_proximity", 0.5))
            if strategy == "rolling_ilp":
                ilp_window_days = int(
                    st.slider("Planning window (days)", min_value=14, max_value=180, value=ilp_window_days)
                )
                ilp_weight_coverage = float(
                    st.slider("Weight: coverage (avoid missed MTBT)", min_value=0.0, max_value=50.0, value=ilp_weight_coverage, step=0.5)
                )
                ilp_weight_travel = float(
                    st.slider("Weight: travel cost", min_value=0.0, max_value=10.0, value=ilp_weight_travel, step=0.1)
                )
                ilp_weight_proximity = float(
                    st.slider("Weight: proximity to MTBT limit", min_value=0.0, max_value=5.0, value=ilp_weight_proximity, step=0.1)
                )
```

Then in the `if form_submitted:` block right below (around line 154), add:

```python
            config["strategy"] = strategy
            config["ilp_window_days"] = ilp_window_days
            config["ilp_weight_coverage"] = ilp_weight_coverage
            config["ilp_weight_travel"] = ilp_weight_travel
            config["ilp_weight_proximity"] = ilp_weight_proximity
```

- [ ] **Step 2: Pass the new config fields through to the actual run**

Locate the `run_auto_plan_from_args(...)` call inside `render_auto_simulation_page` (around line 187) and add the new keyword arguments:

```python
            plan_result = run_auto_plan_from_args(
                schedule_path,
                start_station=config["start_station"],
                facing_station=config["facing_station"],
                start_year=config["start_year"],
                end_year=config["end_year"],
                steps=config["steps"],
                second_kld=config["second_kld"],
                network_source=callbacks.network_file_path_provider(),
                strategy=config.get("strategy", "greedy"),
                ilp_window_days=config.get("ilp_window_days", 60),
                ilp_weight_coverage=config.get("ilp_weight_coverage", 10.0),
                ilp_weight_travel=config.get("ilp_weight_travel", 1.0),
                ilp_weight_proximity=config.get("ilp_weight_proximity", 0.5),
            )
```

Then in `result_payload = {...}` right below, add `"strategy": plan_result.strategy_name,` as a new key — this is what makes saved runs distinguishable by strategy on the Comparison page (Task 11).

- [ ] **Step 3: Update the `run_auto_plan` wrapper in `streamlit_app.py`**

Read `streamlit_app.py` around line 251 (`def run_auto_plan(...)`) before editing — it's a thin wrapper that already forwards keyword args to `run_auto_plan_from_args` (per the grep from the design phase: `result = run_auto_plan_from_args(...)` at line 263). Add the same 5 new keyword arguments to this wrapper's signature and its forwarding call, mirroring exactly what Step 2 added to `auto_simulation.py`'s direct call — both code paths must accept and forward the same parameters, since `auto_simulation.py` may call either depending on how `streamlit_app.py` wires its callbacks (confirm which one is actually used by checking how `AutoSimulationCallbacks` is constructed in `streamlit_app.py`, and only change the one that's actually on the call path if they turn out to be redundant).

- [ ] **Step 4: Manual verification**

Run: kill any process on port 8501, then `.venv\Scripts\python.exe run_streamlit.py` in the background, then open `http://localhost:8501` and navigate to "Auto Simulation". Confirm:
1. The strategy selectbox defaults to "Greedy (atual)" and running it produces identical results to before this change (spot-check against a saved run from before this plan, if one exists).
2. Selecting "Rolling-horizon ILP" reveals the 4 sliders.
3. Running with "Rolling-horizon ILP" on the real network (`network_20251223_115340.json`, if configured as the active network) completes without a Python exception and produces a result with `strategy_name == "rolling_ilp"` visible somewhere reasonable in the results section (add a `st.caption(f"Strategy: {auto_result.get('strategy', 'greedy')}")` near the top of `_render_auto_run_details` if it isn't already visible anywhere).

- [ ] **Step 5: Commit**

```bash
git add src/railroad_frontend/views/auto_simulation.py streamlit_app.py
git commit -m "feat: expose Auto Planner strategy selector and ILP weight sliders in the UI"
```

---

## Task 11: Comparison page — compare N saved auto runs

**Files:**
- Modify: `src/railroad_frontend/views/comparison.py`
- Modify: `streamlit_app.py` (wherever `render_comparison_page` is called)

**Interfaces:**
- Consumes: `saved_runs` dict from `st.session_state[AUTO_SAVED_RUNS_KEY]` (already populated by `save_auto_run_entry`, Task 10 makes `result["strategy"]` available on each entry going forward — older saved runs without it should be treated as `"greedy"`, since that was the only strategy before this plan).
- Produces: a new function `render_auto_strategy_comparison(saved_runs: Dict[str, Any]) -> None` in `comparison.py`, called from the existing `render_comparison_page` (or from a new tab — whichever fits the existing page structure better; inspect the call site in `streamlit_app.py` before deciding, and prefer adding it as a new `st.tabs()` entry alongside the existing Auto×Manual comparison rather than replacing that comparison).

- [ ] **Step 1: Write the implementation**

Add to `src/railroad_frontend/views/comparison.py`:

```python
def render_auto_strategy_comparison(saved_runs: Dict[str, Any]) -> None:
    """Compare 2+ saved Auto Planner runs (potentially different strategies) side by side."""
    if not saved_runs or len(saved_runs) < 2:
        render_empty_state(
            icon="🧮",
            title="Not Enough Saved Auto Runs",
            description="Save at least 2 Auto Simulation runs (e.g. one Greedy, one Rolling-horizon ILP) to compare strategies here.",
            action_text="Go to Auto Simulation, run a plan, and save it with a descriptive name.",
        )
        return

    st.markdown("### 🧮 Compare saved Auto runs")
    names = sorted(saved_runs.keys())
    selected = st.multiselect("Runs to compare", names, default=names[: min(3, len(names))])
    if len(selected) < 2:
        st.caption("Select at least 2 runs to compare.")
        return

    rows = []
    for name in selected:
        entry = saved_runs[name]
        result = entry.get("result", {})
        idle = result.get("idle_days_total", 0)
        total_days = result.get("movement_days_total", 0) + result.get("maintenance_days_total", 0) + idle
        rows.append(
            {
                "Run": name,
                "Strategy": result.get("strategy", "greedy"),
                "Steps": len(result.get("steps", [])),
                "Maintenance actions": result.get("maintenance_count", 0),
                "Movement days": result.get("movement_days_total", 0),
                "Maintenance days": result.get("maintenance_days_total", 0),
                "Idle days": idle,
                "Total days": total_days,
            }
        )
    comparison_df = pd.DataFrame(rows).set_index("Run")
    st.dataframe(comparison_df, use_container_width=True)
```

Add `render_auto_strategy_comparison` to `comparison.py`'s `__all__`-equivalent (check whether this module has an explicit export list before adding one — match its existing convention).

- [ ] **Step 2: Wire it into the Comparison page**

Read the current `render_comparison_page` call site in `streamlit_app.py` (search for `render_comparison_page(`) to see how `manual_result`/`auto_result` are sourced, and how the page renders (single view vs. tabs). Add a new `st.tabs(["Auto vs Manual", "Compare Auto strategies"])` split (or equivalent existing tab structure if one is already present elsewhere in this file) so the existing Auto×Manual comparison keeps working unchanged in the first tab, and the second tab calls `render_auto_strategy_comparison(st.session_state.get(AUTO_SAVED_RUNS_KEY, {}))`.

- [ ] **Step 3: Manual verification**

With the app running (Task 10, Step 4's relaunch), go to Auto Simulation, run and save one Greedy run and one Rolling-horizon ILP run under different names, then open Comparison and confirm both appear in the multiselect and the table renders with the correct `Strategy` column values.

- [ ] **Step 4: Commit**

```bash
git add src/railroad_frontend/views/comparison.py streamlit_app.py
git commit -m "feat: compare multiple saved Auto Planner runs/strategies on the Comparison page"
```

---

## Task 12: Validate both strategies against the real network and close the loop

**Files:**
- Create: `scripts/compare_auto_strategies.py` (one-off, not a pytest test — mirrors the pattern of `scripts/overnight_manual_route_fuzz.py` from the Manual Route campaign: a real script run against real data, not synthetic fixtures)
- Modify: `SecondBrain/projetos/simulador-esmerilhamento/decisoes.md` (outside this repo — update after running the script, documenting the real numbers)

**Interfaces:**
- Consumes: `run_auto_plan_from_args` with both `strategy="greedy"` and `strategy="rolling_ilp"`, the real network file and a real MTBT schedule CSV (same ones used throughout the Manual Route fuzz campaign — confirm the exact paths with Bruno if `network_20251223_115340.json`'s companion schedule CSV path isn't obvious from `streamlit_app.py`'s `schedule_path_provider`).

- [ ] **Step 1: Write the comparison script**

```python
# scripts/compare_auto_strategies.py
"""One-off script: run Greedy and Rolling-horizon ILP against the real network
and print a side-by-side metrics comparison. Not part of the pytest suite —
run manually: .venv\\Scripts\\python.exe scripts\\compare_auto_strategies.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from railroad_backend.services.auto_planner import run_auto_plan_from_args  # noqa: E402

NETWORK_FILE = Path(__file__).resolve().parent.parent / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE_CSV = Path(__file__).resolve().parent.parent / "data" / "mtbt_schedule.csv"


def _run(strategy: str):
    kwargs = dict(
        csv_path=SCHEDULE_CSV,
        start_station="ZTO",
        facing_station="ZCZ",
        start_year=2026,
        end_year=2027,
        steps=400,
        second_kld=True,
        network_source=NETWORK_FILE,
        strategy=strategy,
    )
    if strategy == "rolling_ilp":
        kwargs.update(ilp_window_days=60, ilp_weight_coverage=10.0, ilp_weight_travel=1.0, ilp_weight_proximity=0.5, ilp_time_limit_s=20.0)
    return run_auto_plan_from_args(**kwargs)


def main() -> None:
    for strategy in ("greedy", "rolling_ilp"):
        result = _run(strategy)
        sim = result.simulator
        idle = getattr(sim, "idle_days_total", 0)
        total = sim.movement_days_total + sim.maintenance_days_total + idle
        print(f"--- {strategy} ---")
        print(f"stop_reason={result.stop_reason} steps={len(sim.steps)} maintenance_count={sim.maintenance_count}")
        print(f"movement_days={sim.movement_days_total} maintenance_days={sim.maintenance_days_total} idle_days={idle} total_days={total}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the real data**

Run: `.venv\Scripts\python.exe scripts\compare_auto_strategies.py`

(`SCHEDULE_CSV` above already points at the real file this repo uses — `streamlit_app.py`'s `DEFAULT_SCHEDULE = DATA_DIR / "mtbt_schedule.csv"`, confirmed present on disk during planning.)

Expected: two blocks of real metrics printed, no exception. Compare `total_days` and `maintenance_count` between the two strategies — this is the actual evidence for whether Rolling-horizon ILP is worth using over Greedy on the real network, which was Bruno's stated goal ("estudar diferentes fatores... buscar uma otimização do recurso").

- [ ] **Step 3: Record the result**

Append a new entry to `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` (top of the file, following the established format) with: the real `total_days`/`maintenance_count`/`idle_days` numbers for both strategies, which one Bruno prefers (or whether neither wins clearly and both stay available), and whether the ILP weights need recalibrating based on what was observed. This is a manual step done together with Bruno, not something to guess at without his input.

- [ ] **Step 4: Commit**

```bash
git add scripts/compare_auto_strategies.py
git commit -m "test: add real-network comparison script for Greedy vs Rolling-horizon ILP"
```

(The `decisoes.md` update lives in the SecondBrain repo, committed separately there if Bruno wants it committed — that repo has its own commit cadence, not tied to this one.)

---

## Post-plan note for the implementer

This plan intentionally stops at 2 strategies. The design spec (`docs/superpowers/specs/2026-08-11-auto-planner-strategy-design.md`) documents Simulated Annealing/Genetic Algorithm and Whittle-index/restless-bandit strategies as candidates for a *future* round, contingent on what Task 12's real-network comparison shows. Do not implement them as part of this plan — that would be scope creep past what was approved.
