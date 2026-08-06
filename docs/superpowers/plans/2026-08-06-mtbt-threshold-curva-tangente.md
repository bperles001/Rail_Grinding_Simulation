# MTBT Threshold Curva/Tangente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single MTBT load/threshold pair on `Segment` into independent curva/tangente pairs, all the way from the data model through the Network Editor UI, auto-planner, and timeline visualization.

**Architecture:** Additive replacement of `Segment.load`/`Segment.mtbt_threshold` with `load_curva`/`load_tangente`/`mtbt_threshold_curva`/`mtbt_threshold_tangente`, following the same flat-sibling-fields pattern already used for `curve_length_km`/`tangent_length_km`. Reset semantics differ by maintenance action (`maintain` resets both, `maintain_curves` resets only curva). Existing network JSON files migrate by duplicating the current single value into both new fields.

**Tech Stack:** Python 3.12, dataclasses (`slots=True`), Streamlit `data_editor`, pytest.

## Global Constraints

- No backward-compat alias for the old `mtbt_threshold`/`load` field names — remove them outright (per repo convention: no compat shims).
- Spec: `docs/superpowers/specs/2026-08-06-mtbt-threshold-curva-tangente-design.md` is authoritative for behavior decisions.
- Run `pytest` (via project `.venv`) after every task; must stay green before moving to the next task.
- Commit after each task (prefixes `feat:`/`fix:`/`data:`/`test:` per project CLAUDE.md).

---

### Task 1: `Segment`/`GrinderMachine` model — dual load/threshold fields

**Files:**
- Modify: `src/models/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Segment.load_curva: float`, `Segment.load_tangente: float`, `Segment.mtbt_threshold_curva: float`, `Segment.mtbt_threshold_tangente: float`, `Segment.maintenance_due: bool` (OR of both), `Segment.maintenance_due_curva: bool`, `Segment.maintenance_due_tangente: bool`, `Segment.add_load(amount: float) -> None`, `Segment.reset_maintenance(component: str = "both") -> None`, `GrinderMachine.perform_maintenance(segment: Segment, component: str = "both") -> bool`.

- [ ] **Step 1: Write failing tests for the new model shape**

Replace the body of `tests/test_models.py` with:

```python
import pytest

from src.models import GrinderMachine, Segment, Station


def _build_segment(threshold_curva: float = 10.0, threshold_tangente: float = 10.0) -> tuple[Station, Station, Segment]:
    start = Station("STA", can_turn=True)
    end = Station("STB")
    segment = Segment(
        name="STA-STB",
        start_station=start,
        end_station=end,
        length=12.5,
        mtbt_threshold_curva=threshold_curva,
        mtbt_threshold_tangente=threshold_tangente,
        move_time_days=2,
        maintenance_time_days=3,
    )
    return start, end, segment


def test_segment_registers_with_stations_and_allowed_movements():
    start, end, segment = _build_segment()
    assert segment in start.segments
    assert segment in end.segments
    assert (start.name, end.name) in segment.allowed_movements
    assert (end.name, start.name) in segment.allowed_movements


def test_add_load_applies_to_both_accumulators_and_flags_independently():
    _, _, segment = _build_segment(threshold_curva=5.0, threshold_tangente=100.0)
    segment.add_load(3)
    assert segment.maintenance_due_curva is False
    assert segment.maintenance_due_tangente is False
    assert segment.maintenance_due is False
    segment.add_load(2.5)
    assert segment.load_curva == pytest.approx(5.5)
    assert segment.load_tangente == pytest.approx(5.5)
    assert segment.maintenance_due_curva is True
    assert segment.maintenance_due_tangente is False
    assert segment.maintenance_due is True


def test_reset_maintenance_curva_only_leaves_tangente_accumulating():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=2.0)
    segment.add_load(2.0)
    assert segment.maintenance_due_curva is True
    assert segment.maintenance_due_tangente is True
    segment.reset_maintenance(component="curva")
    assert segment.load_curva == 0.0
    assert segment.maintenance_due_curva is False
    assert segment.load_tangente == pytest.approx(2.0)
    assert segment.maintenance_due_tangente is True
    assert segment.maintenance_due is True  # tangente still due


def test_reset_maintenance_both_clears_everything():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=2.0)
    segment.add_load(2.0)
    segment.reset_maintenance()
    assert segment.load_curva == 0.0
    assert segment.load_tangente == 0.0
    assert segment.maintenance_due is False


def test_grinder_machine_perform_maintenance_resets_requested_component():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=100.0)
    segment.add_load(2.0)
    grinder = GrinderMachine(front_car_position=segment, rear_car_position=segment, facing="Carregado", global_direction="carregado")
    assert segment.maintenance_due is True
    performed = grinder.perform_maintenance(segment, component="curva")
    assert performed is True
    assert segment.load_curva == 0.0
    assert segment.maintenance_due is False
    assert grinder.mode == "maintenance"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: FAIL — `Segment.__init__() got an unexpected keyword argument 'mtbt_threshold_curva'`.

- [ ] **Step 3: Implement the model changes**

In `src/models/__init__.py`, replace the `Segment` dataclass fields and methods:

```python
@dataclass(slots=True)
class Segment:
    """Directed edge between two stations with MTBT tracking (curva/tangente independent)."""

    name: str
    start_station: Station
    end_station: Station
    length: float = 0.0
    load_curva: float = 0.0
    load_tangente: float = 0.0
    maintenance_due: bool = False
    maintenance_due_curva: bool = False
    maintenance_due_tangente: bool = False
    mtbt_threshold_curva: float = 0.0
    mtbt_threshold_tangente: float = 0.0
    allowed_movements: List[Movement] = field(default_factory=list)
    move_time_days: int = 1
    maintenance_time_days: int = 1
    curve_length_km: float = 0.0
    tangent_length_km: float = 0.0
    move_billed_days: float = 0.0
    maintenance_billed_days: float = 0.0

    def __repr__(self) -> str:
        return (
            f"Segment(name={self.name!r}, start={self.start_station.name!r}, "
            f"end={self.end_station.name!r}, length={self.length})"
        )

    def __post_init__(self) -> None:
        if not self.allowed_movements:
            self.allowed_movements = [
                (self.start_station.name, self.end_station.name),
                (self.end_station.name, self.start_station.name),
            ]
        else:
            cleaned: List[Movement] = []
            for pair in self.allowed_movements:
                if (
                    not isinstance(pair, Sequence)
                    or isinstance(pair, (str, bytes))
                    or len(pair) != 2
                ):
                    continue
                src, dst = pair
                cleaned.append((str(src), str(dst)))
            self.allowed_movements = cleaned or [
                (self.start_station.name, self.end_station.name),
                (self.end_station.name, self.start_station.name),
            ]
        self.start_station.add_segment(self)
        self.end_station.add_segment(self)

    def add_load(self, amount: float) -> None:
        """Add the same MTBT increment to both accumulators and update flags.

        Traffic data (MTBT schedule CSV) is not differentiated by curva/tangente
        today, so both accumulators receive the same increment; only the
        thresholds differ, which is what makes curva and tangente vencer at
        different times once one of them gets reset independently.
        """
        try:
            amount = float(amount)
        except (TypeError, ValueError):  # fall back for Decimal/np types
            pass
        self.load_curva += amount  # type: ignore[operator]
        self.load_tangente += amount  # type: ignore[operator]
        if self.mtbt_threshold_curva and self.load_curva >= self.mtbt_threshold_curva:
            self.maintenance_due_curva = True
        if self.mtbt_threshold_tangente and self.load_tangente >= self.mtbt_threshold_tangente:
            self.maintenance_due_tangente = True
        self.maintenance_due = self.maintenance_due_curva or self.maintenance_due_tangente

    def reset_maintenance(self, component: str = "both") -> None:
        if component not in ("both", "curva", "tangente"):
            raise ValueError(f"component must be 'both', 'curva' or 'tangente', got {component!r}")
        if component in ("both", "curva"):
            self.load_curva = 0.0
            self.maintenance_due_curva = False
        if component in ("both", "tangente"):
            self.load_tangente = 0.0
            self.maintenance_due_tangente = False
        self.maintenance_due = self.maintenance_due_curva or self.maintenance_due_tangente

    def increment_mtbt(self) -> None:
        self.add_load(1.0)

    def add_mtbt(self, amount: float) -> None:
        self.add_load(amount)
```

And update `GrinderMachine.perform_maintenance`:

```python
    def perform_maintenance(self, segment: Segment, component: str = "both") -> bool:
        if hasattr(segment, "reset_maintenance"):
            segment.reset_maintenance(component=component)
            self.mode = "maintenance"
            return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/models/__init__.py tests/test_models.py
git commit -m "feat: split Segment MTBT load/threshold into curva/tangente pairs"
```

---

### Task 2: Simulator core — route reset to the right component

**Files:**
- Modify: `src/railroad_backend/domain/simulator.py` (or wherever `move_to` calling `machine.perform_maintenance` lives — confirmed at `src/railroad_backend/domain/simulator.py:318-322` via `Simulator.move_to`)
- Test: `tests/test_edge_cases.py`, `tests/test_direction_logic.py`

**Interfaces:**
- Consumes: `GrinderMachine.perform_maintenance(segment, component)` from Task 1.
- Consumes: `ACTION_MAINTAIN`, `ACTION_MAINTAIN_CURVES` from `src.models`.

- [ ] **Step 1: Write failing test asserting maintain_curves only clears curva**

Add to `tests/test_edge_cases.py` (near the other segment/maintenance tests):

```python
def test_maintain_curves_action_resets_only_curva_component():
    """ACTION_MAINTAIN_CURVES must not clear the tangente accumulator (regression for the
    latent bug where perform_maintenance() ignored which action triggered it)."""
    from src.models import ACTION_MAINTAIN_CURVES

    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = sim.segments[0]
    seg.mtbt_threshold_curva = 1.0
    seg.mtbt_threshold_tangente = 1000.0
    seg.add_load(2.0)
    assert seg.maintenance_due_curva is True
    assert seg.maintenance_due_tangente is False

    sim.machine.global_direction = seg.allowed_movements[0][0].upper() if seg.allowed_movements else None
    sim.machine.second_kld_installed = True  # force perform_maintenance to run regardless of direction
    sim.move_to(seg, seg.end_station, action=ACTION_MAINTAIN_CURVES)

    assert seg.load_curva == 0.0
    assert seg.load_tangente == pytest.approx(2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py::test_maintain_curves_action_resets_only_curva_component -v`
Expected: FAIL — `perform_maintenance()` today resets both components regardless of action (the latent bug from the spec).

- [ ] **Step 3: Fix `move_to` to pass the right component**

In `src/railroad_backend/domain/simulator.py`, find the block (originally around line 318):

```python
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            if machine.second_kld_installed:
                performed = machine.perform_maintenance(seg)
            elif edge_dir == machine.global_direction:
                performed = machine.perform_maintenance(seg)
```

Replace with:

```python
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            if machine.second_kld_installed:
                performed = machine.perform_maintenance(seg, component=component)
            elif edge_dir == machine.global_direction:
                performed = machine.perform_maintenance(seg, component=component)
```

Also update the `mtbt_before` capture a few lines above (originally `mtbt_before = getattr(seg, "load", None)`) to reflect both components:

```python
        mtbt_before_curva = getattr(seg, "load_curva", None)
        mtbt_before_tangente = getattr(seg, "load_tangente", None)
```

...and thread `mtbt_before_curva`/`mtbt_before_tangente` into the returned step dict in place of the old single `mtbt_before` key (replace `"mtbt_before": float(mtbt_before) if isinstance(mtbt_before, (int, float)) else mtbt_before,` with two keys `"mtbt_before_curva"` and `"mtbt_before_tangente"` following the same ternary pattern).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py tests/test_direction_logic.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/domain/simulator.py tests/test_edge_cases.py
git commit -m "fix: maintain_curves now resets only the curva MTBT component"
```

---

### Task 3: Loader, validation, and existing test fixtures — new JSON schema

**Files:**
- Modify: `src/utils/network_loader.py`
- Modify: `src/railroad_backend/domain/validation.py`
- Test: `tests/test_network_loader.py`, `tests/test_validation.py`, `tests/test_basic.py`, `tests/test_edge_cases.py` (remaining `mtbt_threshold`/`.load` references)

**Interfaces:**
- Produces: JSON segment entries now require `mtbt_threshold_curva` and `mtbt_threshold_tangente` instead of `mtbt_threshold`.

- [ ] **Step 1: Update fixtures and write the new required-field assertion**

In `tests/test_network_loader.py`, replace `"mtbt_threshold": 5` (line 24) with:

```python
                "mtbt_threshold_curva": 5,
                "mtbt_threshold_tangente": 20,
```

Add a new test in the same file:

```python
def test_load_network_rejects_missing_curva_threshold(tmp_path: Path) -> None:
    payload = _base_payload()
    del payload["segments"][0]["mtbt_threshold_curva"]
    path = tmp_path / "network.json"
    _write_network(path, payload)
    with pytest.raises(NetworkConfigError):
        load_network(path)
```

(add `import pytest` at top if not present)

In `tests/test_validation.py` line 177, replace `"mtbt_threshold": 100,` with `"mtbt_threshold_curva": 100, "mtbt_threshold_tangente": 100,`.

In `tests/test_basic.py` line 122, replace `"mtbt_threshold": 1,` with `"mtbt_threshold_curva": 1, "mtbt_threshold_tangente": 1,`.

In `tests/test_edge_cases.py`, fix remaining references (lines ~145-146, ~157-158, ~181-182, ~240-251, ~274-289 identified in Task 1/2 grep):
- `seg = Segment("A-B", start, end, 10, 0.0, 1, 1)` → `seg = Segment("A-B", start, end, length=10)` (drop the old positional `load`/`mtbt_threshold` args, set fields by keyword after construction as the test already does).
- `seg.mtbt_threshold = None` → `seg.mtbt_threshold_curva = None; seg.mtbt_threshold_tangente = None`
- `seg.load = 1000` → `seg.load_curva = 1000; seg.load_tangente = 1000`
- Apply the analogous curva/tangente rename to every remaining bare `seg.load`/`seg.mtbt_threshold` assignment in that file (the `_needs_maintenance` calls in Task 4 will then read the new fields).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_network_loader.py tests/test_validation.py tests/test_basic.py -v`
Expected: FAIL — `KeyError: 'mtbt_threshold'` / assertion mismatches.

- [ ] **Step 3: Update the loader and validator**

In `src/utils/network_loader.py`:

```python
_REQUIRED_SEGMENT_FIELDS = {"name", "start", "end", "length_km", "mtbt_threshold_curva", "mtbt_threshold_tangente", "move_time_days", "maintenance_time_days"}
```

And in `_build_segments`, replace the `Segment(...)` construction's `mtbt_threshold=float(entry["mtbt_threshold"])` line with:

```python
            mtbt_threshold_curva=float(entry["mtbt_threshold_curva"]),
            mtbt_threshold_tangente=float(entry["mtbt_threshold_tangente"]),
```

In `src/railroad_backend/domain/validation.py` line 168:

```python
    required_seg_fields = {"name", "start", "end", "length_km", "mtbt_threshold_curva", "mtbt_threshold_tangente", "move_time_days", "maintenance_time_days"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_network_loader.py tests/test_validation.py tests/test_basic.py tests/test_edge_cases.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/utils/network_loader.py src/railroad_backend/domain/validation.py tests/test_network_loader.py tests/test_validation.py tests/test_basic.py tests/test_edge_cases.py
git commit -m "feat: require mtbt_threshold_curva/tangente in network JSON schema"
```

---

### Task 4: Auto-planner — per-component urgency and action choice

**Files:**
- Modify: `src/railroad_backend/services/auto_planner.py`
- Test: `tests/test_edge_cases.py`

**Interfaces:**
- Consumes: `Segment.load_curva/tangente`, `Segment.mtbt_threshold_curva/tangente`, `Segment.maintenance_due_curva/tangente` from Task 1.
- Produces: `_needs_maintenance(seg) -> bool` (unchanged signature, new internals), new `_maintenance_action_for(seg) -> str` returning `ACTION_MAINTAIN` or `ACTION_MAINTAIN_CURVES`.

- [ ] **Step 1: Write failing tests**

Replace/update the relevant tests in `tests/test_edge_cases.py`:

```python
def test_needs_maintenance_true_when_only_curva_due():
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(5.0)
    assert _needs_maintenance(seg) is True


def test_needs_maintenance_false_when_neither_due():
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(1.0)
    assert _needs_maintenance(seg) is False


def test_maintenance_action_is_curves_only_when_only_curva_due():
    from src.railroad_backend.services.auto_planner import _maintenance_action_for
    from src.models import ACTION_MAINTAIN_CURVES

    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(5.0)
    assert _maintenance_action_for(seg) == ACTION_MAINTAIN_CURVES


def test_maintenance_action_is_full_when_tangente_due():
    from src.railroad_backend.services.auto_planner import _maintenance_action_for
    from src.models import ACTION_MAINTAIN

    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=5.0)
    seg.add_load(5.0)
    assert _maintenance_action_for(seg) == ACTION_MAINTAIN
```

(Remove/replace the now-invalid `test_needs_maintenance_handles_missing_threshold`, `test_needs_maintenance_handles_edge_case_exactly_at_threshold`, `test_simulator_handles_segment_with_zero_threshold`, `test_segment_load_operations` bodies that reference the old single `seg.load`/`seg.mtbt_threshold` — port each to the curva/tangente equivalent using the same pattern shown above.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -v`
Expected: FAIL — `ImportError: cannot import name '_maintenance_action_for'` and `AttributeError` on old fields.

- [ ] **Step 3: Implement in `auto_planner.py`**

Replace `_needs_maintenance` (originally lines 127-143):

```python
def _needs_maintenance(seg) -> bool:
    """Check if segment's curva or tangente load exceeds its threshold.

    Args:
        seg: Segment object with load_curva/load_tangente and
            mtbt_threshold_curva/mtbt_threshold_tangente attributes.

    Returns:
        True if either component needs maintenance.
    """
    return bool(getattr(seg, "maintenance_due_curva", False) or getattr(seg, "maintenance_due_tangente", False))


def _maintenance_action_for(seg) -> str:
    """Pick maintain_curves when only curva is due, full maintain otherwise.

    There is no 'tangente only' action: a full grind covers both components,
    so it's the correct choice whenever tangente is due (curva or not).
    """
    if getattr(seg, "maintenance_due_tangente", False):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES
```

Update the import line (originally `from src.models import ACTION_MAINTAIN, ACTION_MOVE`) to:

```python
from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE
```

In `_apply_initial_loads` (originally lines 89-101), the CSV only carries one "Initial Load" column (out of scope to split per the spec), so apply it to both components:

```python
def _apply_initial_loads(sim: Simulator, csv_path: Path) -> None:
    loads = get_initial_loads(str(csv_path))
    for seg in sim.segments:
        if seg.name in loads:
            seg.load_curva = loads[seg.name]
            seg.load_tangente = loads[seg.name]
            if seg.mtbt_threshold_curva:
                seg.maintenance_due_curva = seg.load_curva >= seg.mtbt_threshold_curva
            if seg.mtbt_threshold_tangente:
                seg.maintenance_due_tangente = seg.load_tangente >= seg.mtbt_threshold_tangente
            seg.maintenance_due = seg.maintenance_due_curva or seg.maintenance_due_tangente
```

In `_days_until_next_threshold` (originally lines 158-200), it scans a single `thresholds`/`projected` dict keyed by segment name. Change it to scan both components and return the minimum days-until-due across all segment/component pairs:

```python
def _days_until_next_threshold(sim: Simulator, *, scan_limit_days: int = 180) -> int:
    if not sim.daily_map or not sim.simulation_date:
        return 0
    projected: Dict[str, float] = {}
    thresholds: Dict[str, float] = {}
    for seg in sim.segments:
        for component, threshold, load in (
            (f"{seg.name}::curva", seg.mtbt_threshold_curva, seg.load_curva),
            (f"{seg.name}::tangente", seg.mtbt_threshold_tangente, seg.load_tangente),
        ):
            if threshold in (None, 0):
                continue
            thresholds[component] = float(threshold)
            projected[component] = float(load or 0.0)
    if not thresholds:
        return 0
    if _segments_already_due(sim):
        return 0
    seg_name_by_component = {f"{seg.name}::curva": seg.name for seg in sim.segments}
    seg_name_by_component.update({f"{seg.name}::tangente": seg.name for seg in sim.segments})
    cached_daily_vals = {
        component: sim.daily_map.get(seg_name_by_component[component]) or {}
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
```

In `_perform_next_step` (originally line 239), replace:

```python
        action = ACTION_MAINTAIN if _needs_maintenance(seg) else ACTION_MOVE
```

with:

```python
        action = _maintenance_action_for(seg) if _needs_maintenance(seg) else ACTION_MOVE
```

In `_move_priority` (originally lines 203-215), `load = float(getattr(seg, "load", 0.0) or 0.0)` should become the worst-case of the two components for sorting purposes:

```python
def _move_priority(pair) -> Tuple[int, float, str]:
    seg, _ = pair
    urgent = 0 if _needs_maintenance(seg) else 1
    load = max(
        float(getattr(seg, "load_curva", 0.0) or 0.0),
        float(getattr(seg, "load_tangente", 0.0) or 0.0),
    )
    return (urgent, -load, seg.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/services/auto_planner.py tests/test_edge_cases.py
git commit -m "feat: auto-planner decides maintain vs maintain_curves per component urgency"
```

---

### Task 5: Network Editor domain/service layer — two DataFrame columns

**Files:**
- Modify: `src/railroad_backend/domain/network_editor.py`
- Modify: `src/railroad_backend/services/network_editor.py`
- Test: `tests/test_network_editor.py`

**Interfaces:**
- Produces: `network_editor_segment_df` DataFrame columns `"MTBT threshold (curva)"` / `"MTBT threshold (tangente)"` instead of `"MTBT threshold"`.
- Consumes: none new (pure pandas/dict transforms).

- [ ] **Step 1: Update fixtures and write failing assertions**

In `tests/test_network_editor.py`, replace `"mtbt_threshold": 5.0,` (line 23) with `"mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,`.

Add:

```python
def test_segment_dataframe_splits_mtbt_threshold_columns():
    df = network_editor.network_editor_segment_df(_base_payload())
    assert "MTBT threshold (curva)" in df.columns
    assert "MTBT threshold (tangente)" in df.columns
    assert "MTBT threshold" not in df.columns
    assert df.loc[0, "MTBT threshold (curva)"] == 5.0
    assert df.loc[0, "MTBT threshold (tangente)"] == 20.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_network_editor.py -v`
Expected: FAIL — `KeyError: 'MTBT threshold (curva)'`.

- [ ] **Step 3: Update `network_editor_segment_df`**

In `src/railroad_backend/domain/network_editor.py`, in the `rows.append({...})` dict (originally line 59), replace:

```python
                "MTBT threshold": entry.get("mtbt_threshold", 0.0),
```

with:

```python
                "MTBT threshold (curva)": entry.get("mtbt_threshold_curva", 0.0),
                "MTBT threshold (tangente)": entry.get("mtbt_threshold_tangente", 0.0),
```

Do the same replacement in the empty-DataFrame `columns=[...]` list (originally line 77) and in both numeric-coercion tuples (originally lines 87 and — check for a second occurrence further down in the same file used for the empty-df branch).

- [ ] **Step 4: Update `serialize_network_editor_state` and diff summary**

In `src/railroad_backend/services/network_editor.py`, replace (originally line 465):

```python
            threshold = float(row.get("MTBT threshold", 0.0) or 0.0)
```

with:

```python
            threshold_curva = float(row.get("MTBT threshold (curva)", 0.0) or 0.0)
            threshold_tangente = float(row.get("MTBT threshold (tangente)", 0.0) or 0.0)
```

and the segment dict literal (originally line 480):

```python
            "mtbt_threshold": threshold,
```

with:

```python
            "mtbt_threshold_curva": threshold_curva,
            "mtbt_threshold_tangente": threshold_tangente,
```

In `network_editor_diff_summary`'s `compare_fields` tuple (originally line 317), replace `"mtbt_threshold",` with `"mtbt_threshold_curva", "mtbt_threshold_tangente",`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_network_editor.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/domain/network_editor.py src/railroad_backend/services/network_editor.py tests/test_network_editor.py
git commit -m "feat: Network Editor dataframe/serializer split MTBT threshold curva/tangente"
```

---

### Task 6: Network Editor UI + quick-add form — visible table columns

**Files:**
- Modify: `src/railroad_frontend/views/network_editor.py`
- Modify: `streamlit_app.py`
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `network_editor_segment_df` columns from Task 5.

- [ ] **Step 1: Update fixture and write a failing UI test**

In `tests/test_streamlit_app_ui.py`, replace both `"mtbt_threshold": 5.0,` occurrences (lines 31, 40) with `"mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,`.

Add a new test in the same file (mirroring the existing `_open_network_editor` helper pattern already in the file):

```python
def test_segments_table_shows_curva_and_tangente_columns(tmp_path: Path):
    at = _open_network_editor(tmp_path)
    at.session_state["active_network_path"]  # sanity: fixture wired
    at.run()
    editors = [w for w in at.get("data_editor") if "segment_editor" in str(w.key)]
    assert editors, "segment data_editor not found"
    columns = list(editors[0].value.columns)
    assert "MTBT threshold (curva)" in columns
    assert "MTBT threshold (tangente)" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: FAIL (column not present / KeyError from the fixture's old field name propagating through the loader).

- [ ] **Step 3: Update the Network Editor view**

In `src/railroad_frontend/views/network_editor.py`:

`column_order` list (originally line 216): replace `"MTBT threshold",` with `"MTBT threshold (curva)", "MTBT threshold (tangente)",`.

`column_config` dict (originally line 246): replace

```python
                "MTBT threshold": st.column_config.NumberColumn("MTBT threshold", min_value=0.0, step=10.0),
```

with

```python
                "MTBT threshold (curva)": st.column_config.NumberColumn(
                    "MTBT threshold (curva)", min_value=0.0, step=10.0,
                    help="Limite de MTBT acumulado para a componente de curva deste trecho.",
                ),
                "MTBT threshold (tangente)": st.column_config.NumberColumn(
                    "MTBT threshold (tangente)", min_value=0.0, step=10.0,
                    help="Limite de MTBT acumulado para a componente de tangente deste trecho.",
                ),
```

Numeric-coercion tuple (originally line 282): replace `"MTBT threshold",` with `"MTBT threshold (curva)", "MTBT threshold (tangente)",`.

Validation block (originally lines 296-297, 314-315): replace

```python
        mtbt = segment_editor.at[idx, "MTBT threshold"]
```

with

```python
        mtbt_curva = segment_editor.at[idx, "MTBT threshold (curva)"]
        mtbt_tangente = segment_editor.at[idx, "MTBT threshold (tangente)"]
```

and

```python
        if mtbt < 0:
            validation_errors.append(f"Row {row_num}: MTBT threshold cannot be negative")
```

with

```python
        if mtbt_curva < 0:
            validation_errors.append(f"Row {row_num}: MTBT threshold (curva) cannot be negative")
        if mtbt_tangente < 0:
            validation_errors.append(f"Row {row_num}: MTBT threshold (tangente) cannot be negative")
```

- [ ] **Step 4: Update the quick-add blank-network defaults**

In `streamlit_app.py`, in `_create_blank_network_file` (originally line 443), replace:

```python
                "mtbt_threshold": 1000.0,
```

with:

```python
                "mtbt_threshold_curva": 1000.0,
                "mtbt_threshold_tangente": 1000.0,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_frontend/views/network_editor.py streamlit_app.py tests/test_streamlit_app_ui.py
git commit -m "feat: Segments table shows separate MTBT threshold columns for curva/tangente"
```

---

### Task 7: Timeline — combined label, worst-case color

**Files:**
- Modify: `src/simulator/timeline.py`
- Modify: `src/utils/timeline_generator.py`
- Test: create `tests/test_timeline.py` if no direct unit test exists yet for `prepare_timeline_rows`/`_get_label_color` (check first; if `tests/test_basic.py` or another file already covers `prepare_timeline_rows`, add cases there instead).

**Interfaces:**
- Consumes: `step["mtbt_before_curva"]`, `step["mtbt_before_tangente"]` produced by Task 2's `move_to` change.
- Produces: timeline rows carry `mtbt_before_curva`, `mtbt_before_tangente`, `mtbt_threshold_curva`, `mtbt_threshold_tangente` instead of the old single-value keys; `_get_label_color` and label text use both.

- [ ] **Step 1: Write failing tests**

Create `tests/test_timeline.py`:

```python
from src.models import Segment, Station
from src.simulator.timeline import prepare_timeline_rows
from src.utils.timeline_generator import TimelineGenerator


def _segment(threshold_curva=10.0, threshold_tangente=30.0):
    a = Station("A")
    b = Station("B")
    return Segment(name="A-B", start_station=a, end_station=b, length=1.0,
                   mtbt_threshold_curva=threshold_curva, mtbt_threshold_tangente=threshold_tangente)


def test_prepare_timeline_rows_carries_both_thresholds_and_loads():
    seg = _segment()
    report = [{
        "segment": "A-B", "action": "maintenance",
        "mtbt_before_curva": 8.0, "mtbt_before_tangente": 25.0,
        "start": "2026-01-01", "end": "2026-01-02",
    }]
    rows, _, _ = prepare_timeline_rows(report, segments=[seg])
    assert rows[0]["mtbt_threshold_curva"] == 10.0
    assert rows[0]["mtbt_threshold_tangente"] == 30.0
    assert rows[0]["mtbt_before_curva"] == 8.0
    assert rows[0]["mtbt_before_tangente"] == 25.0


def test_label_color_is_red_when_worse_component_exceeds_threshold():
    gen = TimelineGenerator.__new__(TimelineGenerator)  # bypass __init__ (no report needed for this unit)
    # curva 8/10 (80%) vs tangente 29/30 (96.7%) -> worst case still under 100%, expect black
    assert gen._get_label_color("maintenance", {"curva": 8.0, "tangente": 29.0}, {"curva": 10.0, "tangente": 30.0}) == "black"
    # tangente now over threshold -> red
    assert gen._get_label_color("maintenance", {"curva": 8.0, "tangente": 31.0}, {"curva": 10.0, "tangente": 30.0}) == "red"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_timeline.py -v`
Expected: FAIL — `KeyError`/`TypeError` on old single-value keys and old `_get_label_color` signature.

- [ ] **Step 3: Update `timeline.py`**

Replace `_create_timeline_row` and the threshold-caching block in `prepare_timeline_rows`:

```python
def _create_timeline_row(
    action: str,
    label: str,
    step: Dict[str, Any],
    segment_thresholds: Dict[str, Dict[str, Optional[float]]],
) -> Optional[Dict[str, Any]]:
    thresholds = segment_thresholds.get(label, {"curva": None, "tangente": None})
    base_row = {
        "step": label,
        "start_time": step.get("start"),
        "end_time": step.get("end"),
        "mtbt_threshold_curva": thresholds.get("curva"),
        "mtbt_threshold_tangente": thresholds.get("tangente"),
    }

    if action in ("move", "maintenance", "maintenance_curves"):
        base_row["status"] = action
        base_row["mtbt_before_curva"] = step.get("mtbt_before_curva", None)
        base_row["mtbt_before_tangente"] = step.get("mtbt_before_tangente", None)
        return base_row
    elif action == "wait":
        base_row["status"] = "wait"
        base_row["mtbt_before_curva"] = None
        base_row["mtbt_before_tangente"] = None
        return base_row
    elif action == "turn":
        base_row["status"] = "turn"
        base_row["mtbt_before_curva"] = None
        base_row["mtbt_before_tangente"] = None
        return base_row
    return None
```

And in `prepare_timeline_rows`, replace the threshold-caching block:

```python
    segment_thresholds: Dict[str, Dict[str, Optional[float]]] = {}
    if segments:
        segment_thresholds = {
            _base_label(seg_obj.name): {
                "curva": getattr(seg_obj, "mtbt_threshold_curva", None),
                "tangente": getattr(seg_obj, "mtbt_threshold_tangente", None),
            }
            for seg_obj in segments
        }
```

- [ ] **Step 4: Update `timeline_generator.py`**

Replace `_should_add_label` and `_get_label_color` (originally lines 192-211):

```python
    def _should_add_label(self, status: str, mtbt_before: Any) -> Tuple[bool, Optional[str]]:
        """Determine if label should be added and what text to use."""
        if status == 'turn':
            return True, 'turn'
        curva = (mtbt_before or {}).get('curva')
        tangente = (mtbt_before or {}).get('tangente')
        parts = []
        if isinstance(curva, (int, float)) and not pd.isna(curva):
            parts.append(f"C:{curva:.0f}")
        if isinstance(tangente, (int, float)) and not pd.isna(tangente):
            parts.append(f"T:{tangente:.0f}")
        if parts:
            return True, " ".join(parts)
        return False, None

    def _get_label_color(self, status: str, mtbt_before: Any, mtbt_threshold: Any) -> str:
        """Get label color based on status and the worst-case curva/tangente ratio."""
        if status == 'turn':
            return 'black'
        curva_before = (mtbt_before or {}).get('curva')
        tangente_before = (mtbt_before or {}).get('tangente')
        curva_threshold = (mtbt_threshold or {}).get('curva')
        tangente_threshold = (mtbt_threshold or {}).get('tangente')
        for before, threshold in ((curva_before, curva_threshold), (tangente_before, tangente_threshold)):
            if threshold is None:
                continue
            try:
                if float(before) > float(threshold):
                    return 'red'
            except Exception:
                continue
        return 'black'
```

In `process_data`, `mtbt_before` is read straight from the DataFrame row today; update `create_timeline_plot`'s per-row loop (originally lines 303, 337-339) to build dicts instead of scalars:

```python
            mtbt_before = {
                "curva": row.get('mtbt_before_curva', None),
                "tangente": row.get('mtbt_before_tangente', None),
            }
```

and the label-color call site:

```python
                    mtbt_threshold = {
                        "curva": row.get('mtbt_threshold_curva'),
                        "tangente": row.get('mtbt_threshold_tangente'),
                    }
                    label_color = self._get_label_color(status, mtbt_before, mtbt_threshold)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_timeline.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/simulator/timeline.py src/utils/timeline_generator.py tests/test_timeline.py
git commit -m "feat: timeline labels show curva and tangente MTBT together, color by worst case"
```

---

### Task 8: Migrate existing network JSON files

**Files:**
- Modify: `data/networks/default.json`, `data/networks/rumo.json`, `data/networks/teste_cria_o.json`, `data/networks/network_20251223_115340.json`

**Interfaces:** none (data-only).

- [ ] **Step 1: Write and run a one-off migration script**

Create `scripts/migrate_mtbt_threshold.py` (temporary, delete after use):

```python
import json
from pathlib import Path

FILES = [
    "data/networks/default.json",
    "data/networks/rumo.json",
    "data/networks/teste_cria_o.json",
    "data/networks/network_20251223_115340.json",
]

for rel in FILES:
    path = Path(rel)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for seg in payload.get("segments", []):
        if "mtbt_threshold" in seg:
            value = seg.pop("mtbt_threshold")
            seg["mtbt_threshold_curva"] = value
            seg["mtbt_threshold_tangente"] = value
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"migrated {rel}")
```

Run: `.venv\Scripts\python.exe scripts/migrate_mtbt_threshold.py`

- [ ] **Step 2: Verify no `mtbt_threshold` key remains**

Run (bash): `grep -c '"mtbt_threshold"' data/networks/*.json`
Expected: no matches (grep returns non-zero / empty for each file).

- [ ] **Step 3: Run the full suite against the migrated data**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests PASS (this exercises `default.json`/`rumo.json` indirectly through any test that loads `DEFAULT_NETWORK_FILE`).

- [ ] **Step 4: Delete the migration script and commit the data**

```bash
rm scripts/migrate_mtbt_threshold.py
git add data/networks/default.json data/networks/rumo.json data/networks/teste_cria_o.json data/networks/network_20251223_115340.json
git commit -m "data: migrate network files to mtbt_threshold_curva/tangente"
```

---

### Task 9: Full verification and restart the running app

**Files:** none (verification only).

- [ ] **Step 1: Run the complete test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests PASS, no `mtbt_threshold`/`.load` AttributeError leftovers.

- [ ] **Step 2: Grep for any remaining old-field references**

Run (bash): `grep -rn "mtbt_threshold\b" --include=*.py src streamlit_app.py | grep -v "_curva\|_tangente"`
Expected: no output (every remaining hit is part of `_curva`/`_tangente` names or comments).

- [ ] **Step 3: Restart the Streamlit process so the running app picks up the change**

```bash
# find and stop the process from the earlier session (port 8501), then:
.venv\Scripts\python.exe run_streamlit.py
```

Verify: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/_stcore/health` returns `200`.

- [ ] **Step 4: Update CHANGELOG.md `[Unreleased]` section**

Add under `### Added`:

```
- Segment MTBT threshold split into independent `mtbt_threshold_curva` /
  `mtbt_threshold_tangente` (and `load_curva` / `load_tangente`) — Segments
  table now has two threshold columns instead of one. `maintain_curves`
  correctly resets only the curva component (previously reset the whole
  segment, same as full `maintain` — fixed as part of this change). Timeline
  labels show both values; auto-planner picks `maintain_curves` vs full
  `maintain` based on which component is due. Existing network files
  migrated (old single threshold duplicated into both new fields).
```

Commit:

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for MTBT threshold curva/tangente split"
```
