# Corredor Singela + LP/LD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a move through a Singela+LP/LD trio a single logical step that atomically affects both physical segments (MTBT, maintenance, duration), instead of the simulator treating Singela/LP/LD as three alternative routes.

**Architecture:** Replace `_get_possible_moves`'s "one segment per move option" with "the tuple of every segment whose `allowed_movements` covers this specific direction" (naturally yields 1 segment where there's no Singela, 2 where there is). Thread that tuple through `Simulator.move_to()` (now `Union[Segment, Sequence[Segment]]`, backward compatible with every existing single-segment caller), and propagate the shape change through auto-planner, manual-planner, UI, and timeline.

**Tech Stack:** Python 3.12, dataclasses, Streamlit, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-corridor-singela-lp-ld-design.md` is authoritative.
- Corridors without a Singela (pure Carregado/Vazio pairs) must not change behavior at all.
- `Simulator.move_to()` must keep accepting a bare `Segment` (not just a sequence) — every existing call site in tests and `auto_planner.py`/`manual_planner.py` passes one, and there is no reason to force-touch all of them.
- Saved manual plans with the old singular `"segment"` key must still load and replay (read-compat, not a new write format).
- Run `.venv\Scripts\python.exe -m pytest -q` after every task; must stay green.
- Commit after each task.

---

### Task 1: `_get_possible_moves` resolves the full segment tuple per direction

**Files:**
- Modify: `src/simulator/network_utils.py` (`_get_possible_moves`, currently lines 38-54)
- Modify: `src/simulator/core.py` (`get_possible_moves`, `get_all_moves_any_direction`, currently lines 133-152)
- Modify: `tests/test_direction_logic.py` (`test_simulator_possible_moves_respect_global_direction`, currently lines 16-24)
- Test: `tests/test_edge_cases.py` (new corridor-grouping tests)

**Interfaces:**
- Produces: `_get_possible_moves(segments, station) -> List[Tuple[Tuple[Segment, ...], Station]]` — each entry's segment tuple has 1 element for a normal/Carregado-Vazio-only pair, 2 elements (Singela first, directional last) for a Singela+LP/LD trio, ordered by `len(allowed_movements)` descending so the caller can always treat `tuple[-1]` as "the directional/most specific segment".
- `Simulator.get_possible_moves()` / `get_all_moves_any_direction()` return `List[Tuple[Tuple[Segment, ...], Station]]` (same shape).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_edge_cases.py`:

```python
def _write_trio_network(tmp_path):
    """Two stations linked by Singela + LP (B->A) + LD (A->B), like TAG-TRO."""
    import json
    payload = {
        "name": "trio",
        "stations": [{"name": "A", "can_turn": True}, {"name": "B", "can_turn": True}],
        "segments": [
            {
                "name": "A-B", "start": "A", "end": "B", "length_km": 10.0,
                "mtbt_threshold_curva": 100.0, "mtbt_threshold_tangente": 100.0,
                "move_time_days": 2, "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            },
            {
                "name": "A-B-LD", "start": "A", "end": "B", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["A", "B"]],
            },
            {
                "name": "A-B-LP", "start": "B", "end": "A", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["B", "A"]],
            },
        ],
    }
    path = tmp_path / "trio_network.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_possible_moves_pairs_singela_with_directional_segment(tmp_path):
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    moves = sim.get_all_moves_any_direction()
    assert len(moves) == 1
    segments, destination = moves[0]
    assert destination.name == "B"
    names = {s.name for s in segments}
    assert names == {"A-B", "A-B-LD"}
    # directional segment (the one with a single allowed direction) is last
    assert len(segments[-1].allowed_movements) == 1
    assert segments[-1].name == "A-B-LD"


def test_get_possible_moves_no_singela_still_returns_single_segment():
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    moves = sim.get_all_moves_any_direction()
    assert moves, "expected at least one move on the default network"
    for segments, _station in moves:
        assert len(segments) == 1  # default.json has no Singela+LP/LD trios
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k possible_moves_pairs -v`
Expected: FAIL — `len(moves) == 1` assertion fails (today returns 2 separate entries, one per segment) or unpacking error.

- [ ] **Step 3: Rewrite `_get_possible_moves`**

In `src/simulator/network_utils.py`, replace the function (currently lines 38-54):

```python
def _get_possible_moves(segments: List[Segment], station: Station) -> List[Tuple[Tuple[Segment, ...], Station]]:
    """Return list of (segment_tuple, other_station) for each reachable neighbor.

    Every segment whose `allowed_movements` covers this exact direction is
    included in the tuple, ordered with the most specific segment last
    (`len(allowed_movements) == 1`, i.e. a directional LP/LD/Carregado/Vazio
    segment) — most-restrictive-last means the caller can always treat
    `segment_tuple[-1]` as "the segment nearest the destination". Where a
    station pair has a Singela shared trunk plus a directional LP/LD leg,
    both come back together in one tuple (a single logical move); where
    there's no Singela (plain Carregado/Vazio pair, or an ordinary single
    segment), the tuple has exactly 1 element, unchanged from before.

    Args:
        segments: List of all network segments.
        station: Current station to find valid moves from.

    Returns:
        List of (segment_tuple, destination_station) tuples for legal moves.
    """
    adjacent_segments, adjacent_stations = _get_adjacent(segments, station)
    by_destination: Dict[str, List[Segment]] = {}
    destination_station_by_name: Dict[str, Station] = {}
    for seg, other in zip(adjacent_segments, adjacent_stations):
        by_destination.setdefault(other.name, []).append(seg)
        destination_station_by_name[other.name] = other

    possible: List[Tuple[Tuple[Segment, ...], Station]] = []
    for other_name, candidates in by_destination.items():
        matching = [
            seg for seg in candidates
            if (station.name, other_name) in seg.allowed_movements
        ]
        if not matching:
            continue
        matching.sort(key=lambda seg: len(seg.allowed_movements), reverse=True)
        possible.append((tuple(matching), destination_station_by_name[other_name]))
    return possible
```

- [ ] **Step 4: Update `Simulator.get_possible_moves` / `get_all_moves_any_direction`**

In `src/simulator/core.py`, replace (currently lines 133-152):

```python
    def get_possible_moves(self) -> List[Tuple[Tuple[Segment, ...], Station]]:
        station = self.current_station
        if station is None:
            return []
        pairs = _get_possible_moves(self.segments, station)
        machine = self.machine
        if not machine:
            return pairs
        filtered = []
        for segments, other in pairs:
            directional = segments[-1]
            edge_dir = _classify_directional_segment(directional, station.name)
            if edge_dir is None or edge_dir == machine.global_direction:
                filtered.append((segments, other))
        return filtered

    def get_all_moves_any_direction(self) -> List[Tuple[Tuple[Segment, ...], Station]]:
        station = self.current_station
        if station is None:
            return []
        return _get_possible_moves(self.segments, station)
```

Add the helper `_classify_directional_segment` near the top of `src/simulator/core.py` (module-level function, after the imports, before the `Simulator` class):

```python
def _classify_directional_segment(segment: Segment, from_station_name: str) -> Optional[str]:
    """CARREGADO/VAZIO for a single segment, derived directly from its own
    start/end — no dependency on DirectionModel's (origin, destination) ->
    segment dict, which silently picks one arbitrary winner when more than
    one segment (Singela + a directional leg) covers the same station pair.
    Only ever called with the directional (most-specific) segment of a move,
    so there's no ambiguity to resolve here.
    """
    if segment.start_station.name == from_station_name:
        return "CARREGADO"
    if segment.end_station.name == from_station_name:
        return "VAZIO"
    return None
```

(`Optional` is already imported in `core.py`.)

- [ ] **Step 5: Update the one broken pre-existing test**

In `tests/test_direction_logic.py`, replace `test_simulator_possible_moves_respect_global_direction` (currently lines 16-24):

```python
def test_simulator_possible_moves_respect_global_direction():
    sim = Simulator()
    sim.init_machine(start_station_name="TRO", facing_station_name="TMI", start_year=2025)
    moves = sim.get_possible_moves()
    assert moves, "Expected at least one allowable move"
    direction = sim.machine.global_direction
    for segments, station in moves:
        assert sim.classify_edge_direction(sim.current_station.name, station.name) == direction
        assert all(segment in sim.segments for segment in segments)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py tests/test_direction_logic.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: some pre-existing tests in `auto_planner.py`/`manual_planner.py` call sites will now fail (they unpack the old 2-tuple shape) — that's expected, fixed in Tasks 3-4. If Task 1's own tests and `test_direction_logic.py` pass, commit; leave the rest of the suite red until Task 4 closes it out (note this explicitly in the commit message).

```bash
git add src/simulator/network_utils.py src/simulator/core.py tests/test_edge_cases.py tests/test_direction_logic.py
git commit -m "feat: get_possible_moves resolves the full segment tuple (Singela+directional) per direction

Downstream callers (auto_planner, manual_planner) still unpack the old
2-tuple shape at this point in the branch -- fixed in the next two tasks."
```

---

### Task 2: `Simulator.move_to()` accepts a segment or a sequence of segments

**Files:**
- Modify: `src/simulator/core.py` (`move_to`, currently lines 257-361ish)
- Test: `tests/test_edge_cases.py`

**Interfaces:**
- Consumes: `_classify_directional_segment` from Task 1.
- Produces: `Simulator.move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None) -> Dict[str, object]`. A bare `Segment` is wrapped into a 1-tuple internally — every existing caller passing a single `Segment` keeps working unchanged. `duration` (when no override) is now the **sum** of `move_time_days`/`maintenance_time_days` across all segments passed. Every segment gets `add_load`/`reset_maintenance` applied. The returned step dict gains `"segments": [s.name for s in segments]` alongside the existing `"segment"` key (now pointing at the *last*/most-specific segment, for every existing reader of `step["segment"]` to keep working unchanged).

- [ ] **Step 1: Update the failing-input test and add corridor-move tests**

In `tests/test_edge_cases.py`, update `test_simulator_move_to_validates_inputs` (the `"seg must be Segment"` match string changes since the parameter is now `segments`):

```python
def test_simulator_move_to_validates_inputs():
    """Simulator.move_to validates segment(s), station, and action."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)

    segment = sim.segments[0]
    station = sim.stations["TMI"]

    # Should reject invalid action code
    with pytest.raises(ValueError, match="action must be"):
        sim.move_to(segment, station, action="invalid")

    # Should reject non-Segment
    with pytest.raises(TypeError, match="segments must contain only Segment instances"):
        sim.move_to("not_a_segment", station, action="v")  # type: ignore[arg-type]

    # Should reject non-Station
    with pytest.raises(TypeError, match="next_station must be Station"):
        sim.move_to(segment, "not_a_station", action="v")  # type: ignore[arg-type]
```

Add new tests (near the trio-network tests added in Task 1 — reuse `_write_trio_network`):

```python
def test_move_to_with_segment_tuple_applies_effects_to_both_and_sums_duration(tmp_path):
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    assert len(segments) == 2

    before = sim.simulation_date
    result = sim.move_to(segments, destination, action="v")
    singela, directional = segments
    # move_time_days: 2 (Singela) + 1 (directional) = 3
    assert (sim.simulation_date - before).days == 3
    assert result["days"] == 3
    assert result["segments"] == ["A-B", "A-B-LD"]
    assert result["segment"] == "A-B-LD"


def test_move_to_maintenance_with_segment_tuple_resets_both(tmp_path):
    from src.models import ACTION_MAINTAIN

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.add_load(10.0)
    directional.add_load(10.0)
    assert singela.maintenance_due is True
    assert directional.maintenance_due is True

    sim.machine.second_kld_installed = True  # force perform_maintenance regardless of direction
    sim.move_to(segments, destination, action=ACTION_MAINTAIN)

    assert singela.load_curva == 0.0 and singela.load_tangente == 0.0
    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0
    # maintenance_time_days: 3 (Singela) + 1 (directional) = 4
    assert sim.steps[-1]["days"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k "move_to" -v`
Expected: FAIL — current `move_to` requires a single `Segment` (`isinstance` check rejects the tuple) and the old error message doesn't match the new regex.

- [ ] **Step 3: Rewrite `move_to`**

In `src/simulator/core.py`, replace the whole method (currently starting at the line
`def move_to(self, seg: Segment, next_station: Station, action: str = "v", duration_override: Optional[int] = None) -> Dict[str, object]:`)
through the point where `mtbt_before_curva`/`mtbt_before_tangente` are captured. The
validation and setup block changes from:

```python
        if not isinstance(seg, Segment):
            raise TypeError(f"seg must be Segment, got {type(seg).__name__}")
        if not isinstance(next_station, Station):
            raise TypeError(f"next_station must be Station, got {type(next_station).__name__}")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(VALID_ACTIONS)!r}, got {action!r}")
        # Normalise legacy single-char codes to canonical names
        if action == "m":
            action = ACTION_MAINTAIN
        elif action == "v":
            action = ACTION_MOVE

        # Validate next_station is an endpoint of seg
        if next_station not in (seg.start_station, seg.end_station):
            raise ValueError(
                f"next_station '{next_station.name}' is not an endpoint of segment '{seg.name}'. "
                f"Valid endpoints: '{seg.start_station.name}', '{seg.end_station.name}'"
            )
```

to:

```python
        def move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None) -> Dict[str, object]:
```

(update the signature line itself — `Union` and `Sequence` need adding to the `typing` import at the top of `core.py`, alongside the existing `Any, Dict, List, Optional, Tuple`)

```python
        if isinstance(segments, Segment):
            segments = (segments,)
        else:
            try:
                segments = tuple(segments)
            except TypeError:
                raise TypeError(f"segments must be a Segment or a sequence of Segment, got {type(segments).__name__}")
        if not segments or not all(isinstance(s, Segment) for s in segments):
            raise TypeError(f"segments must contain only Segment instances, got {[type(s).__name__ for s in segments]!r}")
        if not isinstance(next_station, Station):
            raise TypeError(f"next_station must be Station, got {type(next_station).__name__}")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(VALID_ACTIONS)!r}, got {action!r}")
        # Normalise legacy single-char codes to canonical names
        if action == "m":
            action = ACTION_MAINTAIN
        elif action == "v":
            action = ACTION_MOVE

        # seg is the directional/most-specific segment (last in the tuple, see
        # _get_possible_moves) -- it's the one that determines endpoints,
        # direction classification, and the machine's resting position.
        seg = segments[-1]
        # Validate next_station is an endpoint of seg
        if next_station not in (seg.start_station, seg.end_station):
            raise ValueError(
                f"next_station '{next_station.name}' is not an endpoint of segment '{seg.name}'. "
                f"Valid endpoints: '{seg.start_station.name}', '{seg.end_station.name}'"
            )
```

Next, the segment-resolution fallback block (currently right after, `if (current_station.name, next_station.name) not in getattr(seg, "allowed_movements", []):` ... `seg = candidate; break`) stays exactly as-is — it operates on `seg` (the directional one), unchanged.

The direction classification line changes from:

```python
        edge_dir = self._direction_model.classify(current_station.name, next_station.name)
```

to:

```python
        edge_dir = _classify_directional_segment(seg, current_station.name)
```

The MTBT-before capture block changes from:

```python
        mtbt_before_curva = getattr(seg, "load_curva", None)
        mtbt_before_tangente = getattr(seg, "load_tangente", None)
```

to (still reads from `seg`, the directional one — unchanged, matches spec item 2 "captura do último segmento"):

```python
        mtbt_before_curva = getattr(seg, "load_curva", None)
        mtbt_before_tangente = getattr(seg, "load_tangente", None)
```

(no change needed here — already reads from `seg`, which now correctly refers to the last/directional element of `segments`).

Now the maintenance/duration block. Replace:

```python
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            if machine.second_kld_installed:
                performed = machine.perform_maintenance(seg, component=component)
            elif edge_dir == machine.global_direction:
                performed = machine.perform_maintenance(seg, component=component)

        if performed:
            duration = duration_override if duration_override is not None else seg.maintenance_time_days
            self.maintenance_days_total += duration
            self.maintenance_count += 1
            self.maintenance_log.append((seg.name, None, duration))
        else:
            duration = duration_override if duration_override is not None else seg.move_time_days
            self.movement_days_total += duration
            if not self.daily_map:
                seg.increment_mtbt()
```

with:

```python
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            if machine.second_kld_installed or edge_dir == machine.global_direction:
                for component_seg in segments:
                    machine.perform_maintenance(component_seg, component=component)
                performed = True

        if performed:
            duration = duration_override if duration_override is not None else sum(s.maintenance_time_days for s in segments)
            self.maintenance_days_total += duration
            self.maintenance_count += 1
            self.maintenance_log.append((seg.name, None, duration))
        else:
            duration = duration_override if duration_override is not None else sum(s.move_time_days for s in segments)
            self.movement_days_total += duration
            if not self.daily_map:
                for component_seg in segments:
                    component_seg.increment_mtbt()
```

Finally, `machine.front_car_position = seg` (a few lines above the maintenance block, already present, unchanged — `seg` is `segments[-1]`, the directional/nearest-to-destination one, matching spec item 2).

The returned step dict's `"segment"` key (currently `"segment": seg.name,`) gains a sibling:

```python
                "segment": seg.name,
                "segments": [s.name for s in segments],
```

(insert `"segments": [s.name for s in segments],` right after the existing `"segment": seg.name,` line in the dict literal built at the end of `move_to`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k "move_to" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: Task 1 + Task 2 tests pass; `auto_planner.py`/`manual_planner.py` tests still red (unpacking the old shape) until Task 3-4. Commit with the same caveat as Task 1.

```bash
git add src/simulator/core.py tests/test_edge_cases.py
git commit -m "feat: Simulator.move_to accepts a Segment or a sequence, sums duration/effects across all of them

Downstream callers still unpack the old shape at this point in the
branch -- fixed in the next two tasks."
```

---

### Task 3: Auto-planner works with segment tuples

**Files:**
- Modify: `src/railroad_backend/services/auto_planner.py` (`_needs_maintenance`, `_maintenance_action_for`, `_move_priority`, `_perform_next_step`, `_component_due` — currently around lines 127-249)
- Test: `tests/test_edge_cases.py`

**Interfaces:**
- Consumes: `sim.get_possible_moves()`/`get_all_moves_any_direction()` returning `List[Tuple[Tuple[Segment, ...], Station]]` (Task 1); `Simulator.move_to(segments, ...)` accepting a sequence (Task 2).
- Produces: `_needs_maintenance(segments: Sequence[Segment]) -> bool`, `_maintenance_action_for(segments: Sequence[Segment]) -> str` — both now take a sequence instead of a single segment (call sites elsewhere in this file, and `_days_until_next_threshold`'s per-segment scan, are unaffected since they already iterate `sim.segments` directly, one physical segment at a time — not through `get_possible_moves`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_edge_cases.py`:

```python
def test_auto_planner_needs_maintenance_and_action_over_segment_tuple(tmp_path):
    from railroad_backend.services.auto_planner import _maintenance_action_for, _needs_maintenance
    from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, _destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments

    assert _needs_maintenance(segments) is False

    directional.add_load(20.0)  # only the directional's tangente threshold (20.0) is hit
    assert _needs_maintenance(segments) is True
    assert _maintenance_action_for(segments) == ACTION_MAINTAIN  # tangente due -> full maintain

    directional.reset_maintenance()
    singela.mtbt_threshold_curva = 5.0
    singela.add_load(5.0)  # only curva due, on the Singela this time
    assert _needs_maintenance(segments) is True
    assert _maintenance_action_for(segments) == ACTION_MAINTAIN_CURVES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k needs_maintenance_and_action_over -v`
Expected: FAIL — `_needs_maintenance`/`_maintenance_action_for` currently take a single `seg`, calling `getattr(segments, ...)` on a tuple returns `None`/wrong results.

- [ ] **Step 3: Update `auto_planner.py`**

Replace `_component_due`, `_needs_maintenance`, `_maintenance_action_for` (currently):

```python
def _component_due(seg, component: str) -> bool:
    """..."""
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    load = getattr(seg, f"load_{component}", 0.0) or 0.0
    if threshold is None:
        return False
    try:
        return float(load) >= float(threshold)
    except (TypeError, ValueError):  # pragma: no cover
        return False


def _needs_maintenance(seg) -> bool:
    """..."""
    return _component_due(seg, "curva") or _component_due(seg, "tangente")


def _maintenance_action_for(seg) -> str:
    """..."""
    if _component_due(seg, "tangente"):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES
```

with:

```python
def _component_due(seg, component: str) -> bool:
    """Check if a single component (curva or tangente) has reached its threshold.

    Mirrors the pre-split semantics: an explicit 0 threshold still counts as
    "configured" (>= comparison applies); only a `None` threshold means "not
    configured" and never triggers maintenance.
    """
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    load = getattr(seg, f"load_{component}", 0.0) or 0.0
    if threshold is None:
        return False
    try:
        return float(load) >= float(threshold)
    except (TypeError, ValueError):  # pragma: no cover
        return False


def _needs_maintenance(segments) -> bool:
    """Check if any of the segments in this move (Singela + directional, or
    just the one segment where there's no Singela) has a component due.

    Args:
        segments: A single Segment, or a sequence of Segment (a move option
            from get_possible_moves() carries 1-2 physical segments).

    Returns:
        True if any segment/component combination needs maintenance.
    """
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    return any(_component_due(seg, "curva") or _component_due(seg, "tangente") for seg in seq)


def _maintenance_action_for(segments) -> str:
    """Pick maintain_curves when only curva is due across all segments in
    this move, full maintain when any segment's tangente is due.

    There is no "tangente only" action: a full grind covers both
    components, so it's the correct choice whenever tangente is due on
    either the Singela or the directional segment.
    """
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    if any(_component_due(seg, "tangente") for seg in seq):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES
```

Now `_move_priority` and `_perform_next_step` (currently):

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

becomes:

```python
def _move_priority(pair) -> Tuple[int, float, str]:
    segments, _ = pair
    urgent = 0 if _needs_maintenance(segments) else 1
    load = max(
        max(
            float(getattr(seg, "load_curva", 0.0) or 0.0),
            float(getattr(seg, "load_tangente", 0.0) or 0.0),
        )
        for seg in segments
    )
    name = "+".join(seg.name for seg in segments)
    return (urgent, -load, name)
```

And in `_perform_next_step` (currently):

```python
        seg, next_station = sorted(options, key=_move_priority)[0]
        action = _maintenance_action_for(seg) if _needs_maintenance(seg) else ACTION_MOVE
        sim.move_to(seg, next_station, action=action)
        return True
```

becomes:

```python
        segments, next_station = sorted(options, key=_move_priority)[0]
        action = _maintenance_action_for(segments) if _needs_maintenance(segments) else ACTION_MOVE
        sim.move_to(segments, next_station, action=action)
        return True
```

`_segments_already_due` (`any(_needs_maintenance(seg) for seg in sim.segments)`) is unaffected — it already iterates single physical segments straight from `sim.segments`, not through `get_possible_moves`, and `_needs_maintenance` accepts a bare segment fine (the `isinstance` check wraps it in a 1-tuple).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -v`
Expected: PASS (including the pre-existing `_needs_maintenance`/`_maintenance_action_for` tests from the earlier MTBT-split work, which pass a bare `Segment` — still supported).

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: `tests/test_basic.py::test_run_auto_plan_generates_steps` and other auto-planner integration tests should now pass again (they exercise `run_auto_plan` end-to-end on `default.json`, which has no trios, so behavior is unchanged there).

```bash
git add src/railroad_backend/services/auto_planner.py tests/test_edge_cases.py
git commit -m "feat: auto-planner evaluates maintenance urgency/action over the full segment tuple of a move"
```

---

### Task 4: Manual planner and validation work with segment tuples

**Files:**
- Modify: `src/railroad_backend/services/manual_planner.py` (`ManualMoveOption`, `_find_segment_for_move`, `_handle_move_step`, `list_available_moves` — currently lines 87-239)
- Modify: `src/railroad_backend/domain/validation.py` (`validate_manual_plan_step`, currently lines 87-95)
- Test: `tests/test_edge_cases.py`, `tests/test_integration.py`, `tests/test_validation.py`

**Interfaces:**
- Consumes: `sim.get_possible_moves()`/`get_all_moves_any_direction()` (Task 1), `Simulator.move_to(segments, ...)` (Task 2).
- Produces: `ManualMoveOption.segments: Tuple[str, ...]` (replaces `.segment: str`). `_find_segments_for_move(sim, segment_names, destination) -> Optional[Tuple[Segment, ...]]` (replaces `_find_segment_for_move`). Plan step dicts for `mode == "move"` gain a `"segments": List[str]` field; `_handle_move_step` reads `step.get("segments") or ([step["segment"]] if "segment" in step else None)` for backward compatibility with plans saved before this change.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_edge_cases.py`:

```python
def test_list_available_moves_reports_segment_tuple_for_trio(tmp_path):
    from railroad_backend.services.manual_planner import list_available_moves

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    options = list_available_moves(sim)
    assert len(options) == 1
    assert options[0].segments == ("A-B", "A-B-LD")
    assert options[0].destination == "B"
```

Add to `tests/test_integration.py`, near the other `replay_manual_plan` tests:

```python
def test_manual_plan_move_step_with_segments_list_traverses_trio(tmp_path):
    """A move step using the new 'segments' (list) field should apply to both
    the Singela and the directional leg."""
    import json

    network_payload = {
        "name": "trio",
        "stations": [{"name": "A", "can_turn": True}, {"name": "B", "can_turn": True}],
        "segments": [
            {
                "name": "A-B", "start": "A", "end": "B", "length_km": 10.0,
                "mtbt_threshold_curva": 100.0, "mtbt_threshold_tangente": 100.0,
                "move_time_days": 2, "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            },
            {
                "name": "A-B-LD", "start": "A", "end": "B", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["A", "B"]],
            },
            {
                "name": "A-B-LP", "start": "B", "end": "A", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["B", "A"]],
            },
        ],
    }
    network_path = tmp_path / "trio_network.json"
    network_path.write_text(json.dumps(network_payload), encoding="utf-8")

    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nA-B,1.0\nA-B-LD,1.0\nA-B-LP,1.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="A",
        facing_station="B",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        network_source=network_path,
    )

    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "action": "v"}]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
    assert result.simulator.steps[-1]["days"] == 3  # 2 (Singela) + 1 (directional)
    assert result.simulator.steps[-1]["segments"] == ["A-B", "A-B-LD"]


def test_manual_plan_move_step_with_legacy_segment_key_still_works(tmp_path):
    """Plans saved before this change use a singular 'segment' string; must
    still replay correctly on a network with no Singela trios (default.json)."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )

    plan = [{"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "v"}]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
```

Update `tests/test_validation.py`: find the existing move-step tests (`test_validate_manual_plan_step_rejects_move_missing_fields` and similar, around lines 85-140) — confirm `validate_manual_plan_step` still requires *one of* `"segment"`/`"segments"`; if a test currently asserts that omitting `"segment"` produces an error, it should still pass unchanged (both old and new step dicts in that file use `"segment"` singular, which remains valid).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k list_available_moves_reports tests/test_integration.py -k manual_plan_move_step -v`
Expected: FAIL — `ManualMoveOption` has no `.segments` attribute yet; `_handle_move_step` doesn't read `"segments"`.

- [ ] **Step 3: Update `manual_planner.py`**

Replace `ManualMoveOption` (currently lines 87-91):

```python
@dataclass(frozen=True)
class ManualMoveOption:
    segments: Tuple[str, ...]
    destination: str
    maintenance_aligned: bool
```

Replace `_find_segment_for_move` (currently lines 94-112) with:

```python
def _find_segments_for_move(sim: Simulator, segment_names: Sequence[str], destination: str) -> Optional[Tuple[Segment, ...]]:
    """Locate the segment tuple matching segment_names that connects the
    current station to destination.

    Args:
        sim: Simulator instance.
        segment_names: Names of the segments to traverse, in the order
            returned by get_possible_moves()/get_all_moves_any_direction()
            (Singela first when present, directional last).
        destination: Name of destination station.

    Returns:
        Tuple of Segment objects (same order as segment_names) or None if
        no matching option is currently available.
    """
    for segments, station in sim.get_all_moves_any_direction():
        if station.name != destination:
            continue
        if tuple(s.name for s in segments) == tuple(segment_names):
            return segments
    return None
```

Update `_handle_move_step` (currently lines 149-180): replace

```python
    dest_name = step.get("destination")  # Changed from next_station
    segment_name = step.get("segment")
    if not dest_name or not segment_name:
        return f"Step {step_idx}: incomplete move definition."

    destination = simulator.stations.get(dest_name)
    if destination is None:
        return f"Step {step_idx}: destination {dest_name} is unknown."

    segment = _find_segment_for_move(simulator, segment_name, dest_name)
    if segment is None:
        current = simulator.current_station.name if simulator.current_station else "unknown"
        return f"Step {step_idx}: segment {segment_name} cannot reach {dest_name} from {current}."

    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    try:
        simulator.move_to(segment, destination, action=action_code, duration_override=duration_override)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Manual plan step %d failed: %s", step_idx, exc)
        return f"Step {step_idx}: failed to execute ({exc})."
    return None
```

with:

```python
    dest_name = step.get("destination")  # Changed from next_station
    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]  # plans saved before the corridor change
    if not dest_name or not segment_names:
        return f"Step {step_idx}: incomplete move definition."

    destination = simulator.stations.get(dest_name)
    if destination is None:
        return f"Step {step_idx}: destination {dest_name} is unknown."

    segments = _find_segments_for_move(simulator, segment_names, dest_name)
    if segments is None:
        current = simulator.current_station.name if simulator.current_station else "unknown"
        return f"Step {step_idx}: segment(s) {segment_names} cannot reach {dest_name} from {current}."

    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    try:
        simulator.move_to(segments, destination, action=action_code, duration_override=duration_override)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Manual plan step %d failed: %s", step_idx, exc)
        return f"Step {step_idx}: failed to execute ({exc})."
    return None
```

Update `list_available_moves` (currently lines 220-239):

```python
def list_available_moves(sim: Simulator) -> List[ManualMoveOption]:
    aligned_pairs = {
        (tuple(seg.name for seg in segments), dest.name)
        for segments, dest in sim.get_possible_moves()
    }
    options: List[ManualMoveOption] = []
    seen = set()
    for segments, dest in sim.get_all_moves_any_direction():
        names = tuple(seg.name for seg in segments)
        key = (names, dest.name)
        if key in seen:
            continue
        seen.add(key)
        options.append(ManualMoveOption(segments=names, destination=dest.name, maintenance_aligned=key in aligned_pairs))
    options.sort(key=lambda item: (0 if item.maintenance_aligned else 1, item.destination))
    return options
```

Add `Sequence` to the existing `typing` import at the top of `manual_planner.py` if not already present (it currently imports `Any, Dict, List, Optional, Sequence, Union` — confirm `Sequence` is there; it already is, per the module's existing signature `plan: Sequence[Dict[str, Any]]`).

- [ ] **Step 4: Update `validation.py`**

In `src/railroad_backend/domain/validation.py`, replace (currently lines 87-88 within `validate_manual_plan_step`):

```python
    if mode == "move":
        if "segment" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'segment' field")
```

with:

```python
    if mode == "move":
        if "segment" not in step and "segments" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires a 'segment' or 'segments' field")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py tests/test_integration.py tests/test_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all green now — this closes out the chain started in Tasks 1-2.

```bash
git add src/railroad_backend/services/manual_planner.py src/railroad_backend/domain/validation.py tests/test_edge_cases.py tests/test_integration.py tests/test_validation.py
git commit -m "feat: manual planner and validation accept segment tuples, keep reading legacy singular 'segment' plans"
```

---

### Task 5: Manual Route UI shows both segments and the direction used

**Files:**
- Modify: `src/railroad_frontend/views/manual.py` (`_manual_plan_dataframe`, `_format_option`, the "Add move" form handler — currently around lines 444-475, 517-566)
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `ManualMoveOption.segments: Tuple[str, ...]` (Task 4).
- Produces: the "Next station" dropdown and the plan table's "Segment" column both show `" + ".join(segments)`; new step dicts store `"segments": list(selected_option.segments)` instead of `"segment"`.

- [ ] **Step 1: Write the failing test**

Update the test added in the previous session (`test_manual_plan_dataframe_shows_segment_base_days_for_traverse` in `tests/test_streamlit_app_ui.py`) is unaffected (single-segment case, base days lookup keys off `step.get("segment")` today — see Step 3 below for why it needs a companion, not a replacement). Add a new test:

```python
def test_manual_plan_dataframe_shows_joined_segment_names_for_corridor_step() -> None:
    a = Station("A")
    b = Station("B")
    singela = Segment(name="A-B", start_station=a, end_station=b, length=10.0, move_time_days=2, maintenance_time_days=3)
    directional = Segment(name="A-B-LD", start_station=a, end_station=b, length=1.0, move_time_days=1, maintenance_time_days=1)

    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "action": "v"}]
    df = _manual_plan_dataframe(plan, {}, [singela, directional])
    assert df.loc[0, "Segment"] == "A-B + A-B-LD"
    assert df.loc[0, "Days"] == 3  # 2 (Singela) + 1 (directional)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -k joined_segment_names -v`
Expected: FAIL — `_manual_plan_dataframe` currently reads `step.get("segment", "")` (singular) and looks up a single segment's base days.

- [ ] **Step 3: Update `_manual_plan_dataframe`**

In `src/railroad_frontend/views/manual.py`, in the Traverse branch (the `else:` clause handling non-turn/non-wait steps), replace:

```python
            _act = step.get("action")
            is_maintenance = _act in ("m", "maintain", "maintain_curves")
            seg_obj = segments_by_name.get(step.get("segment"))
            base_days = (seg_obj.maintenance_time_days if is_maintenance else seg_obj.move_time_days) if seg_obj else None
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": step.get("segment", ""),
                "Destination": step.get("destination", ""),
                "Action": (
                    "Maintenance" if _act in ("m", "maintain")
                    else "Curves only" if _act == "maintain_curves"
                    else "Move"
                ),
                "Days": step.get("days_override", base_days),
                "Capability": capability,
            })
```

with:

```python
            _act = step.get("action")
            is_maintenance = _act in ("m", "maintain", "maintain_curves")
            step_segment_names = step.get("segments") or ([step["segment"]] if "segment" in step else [])
            step_seg_objs = [segments_by_name[name] for name in step_segment_names if name in segments_by_name]
            base_days = sum(
                (seg_obj.maintenance_time_days if is_maintenance else seg_obj.move_time_days)
                for seg_obj in step_seg_objs
            ) if step_seg_objs else None
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": " + ".join(step_segment_names),
                "Destination": step.get("destination", ""),
                "Action": (
                    "Maintenance" if _act in ("m", "maintain")
                    else "Curves only" if _act == "maintain_curves"
                    else "Move"
                ),
                "Days": step.get("days_override", base_days),
                "Capability": capability,
            })
```

This also fixes the edit-application loop's base-days lookup a few lines above (the `if _mode == "move":` branch in the `st.data_editor` apply logic) — replace:

```python
                _is_maintenance = _step.get("action") in ("m", "maintain", "maintain_curves")
                _seg_obj = _segments_by_name.get(_step.get("segment"))
                _base_days = (_seg_obj.maintenance_time_days if _is_maintenance else _seg_obj.move_time_days) if _seg_obj else None
```

with:

```python
                _is_maintenance = _step.get("action") in ("m", "maintain", "maintain_curves")
                _step_segment_names = _step.get("segments") or ([_step["segment"]] if "segment" in _step else [])
                _step_seg_objs = [_segments_by_name[name] for name in _step_segment_names if name in _segments_by_name]
                _base_days = sum(
                    (o.maintenance_time_days if _is_maintenance else o.move_time_days) for o in _step_seg_objs
                ) if _step_seg_objs else None
```

- [ ] **Step 4: Update `_format_option` and the "Add move" step construction**

Replace (currently around line 444-447):

```python
            def _format_option(opt: ManualMoveOption) -> str:
                maintenance_note = "maintenance allowed" if maintenance_allowed else "move only"
                return f"{opt.destination} via {opt.segment} ({maintenance_note})"
```

with:

```python
            def _format_option(opt: ManualMoveOption) -> str:
                maintenance_allowed = opt.maintenance_aligned or second_kld_installed
                maintenance_note = "maintenance allowed" if maintenance_allowed else "move only"
                via = " + ".join(opt.segments)
                return f"{opt.destination} via {via} ({maintenance_note})"
```

(note: the original had `maintenance_allowed` computed just above `_format_option` in the enclosing scope already — keep that line where it is; only the body of `_format_option` changes to join `opt.segments` instead of reading `opt.segment`.)

And the step-construction dict (currently around lines 464-471):

```python
                new_plan = plan + [
                    {
                        "mode": "move",
                        "segment": selected_option.segment,
                        "destination": selected_option.destination,
                        "action": action_code,
                    }
                ]
```

becomes:

```python
                new_plan = plan + [
                    {
                        "mode": "move",
                        "segments": list(selected_option.segments),
                        "destination": selected_option.destination,
                        "action": action_code,
                    }
                ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: Manual Route UI shows both segments of a corridor move and the leg used"
```

---

### Task 6: Timeline labels show the directional leg used

**Files:**
- Modify: `src/simulator/timeline.py` (`_create_timeline_row`, `prepare_timeline_rows`, currently the whole file)
- Test: `tests/test_basic.py` (extend the existing `test_prepare_timeline_rows_and_generator`, or add a new focused test)

**Interfaces:**
- Consumes: `step["segments"]` (list, from Task 2's `move_to` step dict) in place of the old singular `step["segment"]` read.
- Produces: `prepare_timeline_rows` labels a corridor step with both segment names joined (e.g. `"A-B + A-B-LD"`) instead of just the directional one.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_basic.py` (near `test_prepare_timeline_rows_and_generator`):

```python
def test_prepare_timeline_rows_labels_corridor_step_with_both_segments():
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "move",
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["step"] == "A-B + A-B-LD"
```

(check the exact import path for `prepare_timeline_rows` already used at the top of `test_basic.py` — reuse it, don't add a new import line if one already exists.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_basic.py -k labels_corridor_step -v`
Expected: FAIL — today's label is `step.get("segment", "")`, i.e. `"A-B-LD"` alone.

- [ ] **Step 3: Update `timeline.py`**

In `src/simulator/timeline.py`, inside `prepare_timeline_rows`, the label-resolution currently does `seg = step.get("segment", "")` then `label = _base_label(seg)`. Replace the per-step label resolution (both in the `move`/`maintenance`/`maintenance_curves` branch and the `wait` branch's `seg or last_step_label` fallback) — find:

```python
    for step in report_data:
        seg = step.get("segment", "")
        action = step.get("action", "move")
        if action in ("move", "maintenance", "maintenance_curves"):
            label = _base_label(seg)
```

and replace with:

```python
    for step in report_data:
        step_segments = step.get("segments") or ([step["segment"]] if step.get("segment") else [])
        seg = " + ".join(step_segments) if step_segments else step.get("segment", "")
        action = step.get("action", "move")
        if action in ("move", "maintenance", "maintenance_curves"):
            label = _base_label(seg)
```

The rest of the function (the `wait`/`turn` branches, `y_order` construction) is unaffected — it already just reuses whatever `seg`/`label` string was computed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_basic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`

```bash
git add src/simulator/timeline.py tests/test_basic.py
git commit -m "feat: timeline labels a corridor step with both segments it touched"
```

---

### Task 7: Full verification, CHANGELOG, and restart the running app

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the complete test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests pass (should be at 150+ tests given the additions across Tasks 1-6).

- [ ] **Step 2: Sanity-check the real "Rumo - Nós" network end-to-end**

```bash
.venv\Scripts\python.exe -c "
from src.simulator import Simulator
sim = Simulator('data/networks/network_20251223_115340.json')
sim.init_machine('TRO', 'TMI', start_year=2026, daily_map=None)
moves = sim.get_all_moves_any_direction()
for segments, dest in moves:
    print([s.name for s in segments], '->', dest.name)
"
```

Expected: at least one move option shows a 2-segment tuple (e.g. `['TAG-TRO', 'TAG-TRO-LD'] -> TRO` or similar, depending on which station TRO/TMI/TAG connect to) — confirms the trio pairing resolves correctly on the network Bruno actually uses, not just the synthetic test fixture.

- [ ] **Step 3: Update CHANGELOG.md `[Unreleased]` section**

Add under `### Fixed` (create the heading if `[Unreleased]` doesn't have one yet — check current file structure first):

```
### Fixed
- Trechos com Singela + Linha Principal/Desviada (LP/LD) agora são tratados
  como um único passo lógico de deslocamento/manutenção que afeta os dois
  segmentos físicos juntos (MTBT, vencimento e duração somados), em vez de
  serem oferecidos como rotas alternativas independentes. Trechos sem
  Singela (só Carregado/Vazio) não mudam. `get_possible_moves()`/
  `Simulator.move_to()` agora trabalham com tuplas de 1-2 segmentos;
  `Simulator.move_to()` continua aceitando um único `Segment` normalmente.
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for the Singela+LP/LD corridor fix"
```

- [ ] **Step 5: Restart the Streamlit process**

```bash
# find the process bound to port 8501 and stop it, then:
.venv\Scripts\python.exe run_streamlit.py
```

Verify: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/_stcore/health` returns `200`.
