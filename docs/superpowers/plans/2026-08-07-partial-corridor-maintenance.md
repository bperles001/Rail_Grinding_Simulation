# Partial Corridor Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Manual Route maintenance step on a 2-segment corridor (Singela + directional) reset only the Singela, only the directional leg, or both — instead of always resetting both.

**Architecture:** `Simulator.move_to()` gains an optional `maintain_segments` allowlist; segments outside it still get traveled (MTBT accumulates, duration counts as movement) but aren't reset. The Manual Route "Add move" form gains a conditional selector wired to this new field.

**Tech Stack:** Python 3.12, Streamlit, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-partial-corridor-maintenance-design.md` is authoritative.
- Auto Simulation (`auto_planner.py`) does not change.
- `maintain_segments=None` (the default, and every existing caller) must reproduce today's exact behavior — maintain every segment in the move, duration = sum of `maintenance_time_days`.
- Run `.venv\Scripts\python.exe -m pytest -q` after every task; must stay green.
- Commit after each task.

---

### Task 1: `Simulator.move_to()` accepts `maintain_segments`

**Files:**
- Modify: `src/simulator/core.py` (`move_to`, currently lines 288-410ish)
- Test: `tests/test_edge_cases.py`

**Interfaces:**
- Produces: `Simulator.move_to(self, segments, next_station, action="v", duration_override=None, maintain_segments: Optional[Sequence[Segment]] = None)`. When maintaining and `maintain_segments` is given, only those segments (which must be a subset of `segments`) get `reset_maintenance()`; every segment not in it still gets traveled (counts as `move_time_days` toward the total duration) but keeps accumulating MTBT untouched by the reset. The step dict gains `"maintained_segments": [s.name for s in <segments actually reset this step>]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_edge_cases.py`:

```python
def test_move_to_maintain_segments_resets_only_the_chosen_leg(tmp_path):
    from src.models import ACTION_MAINTAIN

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.mtbt_threshold_curva = 5.0
    singela.mtbt_threshold_tangente = 5.0
    singela.add_load(10.0)
    directional.add_load(10.0)
    assert singela.maintenance_due is True
    assert directional.maintenance_due is True

    sim.machine.second_kld_installed = True
    sim.move_to(segments, destination, action=ACTION_MAINTAIN, maintain_segments=[directional])

    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0
    assert singela.load_curva == pytest.approx(10.0)  # untouched -- only the directional was chosen
    assert sim.steps[-1]["maintained_segments"] == [directional.name]
    # duration: maintenance_time_days (directional, 1) + move_time_days (Singela, 2) = 3
    assert sim.steps[-1]["days"] == 3


def test_move_to_maintain_segments_none_still_resets_everything(tmp_path):
    from src.models import ACTION_MAINTAIN

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.mtbt_threshold_curva = 5.0
    singela.mtbt_threshold_tangente = 5.0
    singela.add_load(10.0)
    directional.add_load(10.0)

    sim.machine.second_kld_installed = True
    sim.move_to(segments, destination, action=ACTION_MAINTAIN)  # maintain_segments omitted

    assert singela.load_curva == 0.0
    assert directional.load_curva == 0.0
    assert set(sim.steps[-1]["maintained_segments"]) == {"A-B", "A-B-LD"}
    # duration: maintenance_time_days for both: 3 (Singela) + 1 (directional) = 4
    assert sim.steps[-1]["days"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k maintain_segments -v`
Expected: FAIL — `move_to()` has no `maintain_segments` parameter yet, and no `"maintained_segments"` key in the step dict.

- [ ] **Step 3: Implement**

In `src/simulator/core.py`, change the signature:

```python
    def move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None, maintain_segments: Optional[Sequence[Segment]] = None) -> Dict[str, object]:
```

Replace the maintenance/duration block (currently):

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

with:

```python
        maintained: Tuple[Segment, ...] = ()
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            maintain_set = set(maintain_segments) if maintain_segments is not None else set(segments)
            if machine.second_kld_installed or edge_dir == machine.global_direction:
                for component_seg in segments:
                    if component_seg in maintain_set:
                        machine.perform_maintenance(component_seg, component=component)
                maintained = tuple(s for s in segments if s in maintain_set)
                performed = True

        if performed:
            duration = duration_override if duration_override is not None else sum(
                s.maintenance_time_days if s in maintained else s.move_time_days for s in segments
            )
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

And in the returned step dict, add `"maintained_segments"` right after the existing `"segments"` key:

```python
                "segment": seg.name,
                "segments": [s.name for s in segments],
                "maintained_segments": [s.name for s in maintained],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k maintain_segments -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all green (this is additive — every existing call omits `maintain_segments`, defaulting to "maintain everything", identical to today).

```bash
git add src/simulator/core.py tests/test_edge_cases.py
git commit -m "feat: Simulator.move_to accepts maintain_segments to reset only part of a corridor move"
```

---

### Task 2: Manual planner threads `maintain_segments` through

**Files:**
- Modify: `src/railroad_backend/services/manual_planner.py` (`_handle_move_step`, currently lines ~151-184)
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: `Simulator.move_to(..., maintain_segments=...)` from Task 1.
- Produces: `_handle_move_step` reads `step.get("maintain_segments")` (a list of segment names), resolves it to `Segment` objects via `simulator.segments`, and passes the result through. Absent/`None` → passes `None` (maintain everything, today's behavior).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py`, reusing the trio-network payload already defined in `test_manual_plan_move_step_with_segments_list_traverses_trio` (copy the same `network_payload`/`csv_path` setup):

```python
def test_manual_plan_move_step_with_maintain_segments_resets_only_that_leg(tmp_path):
    import json
    from src.models import ACTION_MAINTAIN

    network_payload = {
        "name": "trio",
        "stations": [{"name": "A", "can_turn": True}, {"name": "B", "can_turn": True}],
        "segments": [
            {
                "name": "A-B", "start": "A", "end": "B", "length_km": 10.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 2, "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            },
            {
                "name": "A-B-LD", "start": "A", "end": "B", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["A", "B"]],
            },
            {
                "name": "A-B-LP", "start": "B", "end": "A", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["B", "A"]],
            },
        ],
    }
    network_path = tmp_path / "trio_network.json"
    network_path.write_text(json.dumps(network_payload), encoding="utf-8")

    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,Initial Load,2025-01\nA-B,10.0,1.0\nA-B-LD,10.0,1.0\nA-B-LP,0.0,1.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="A",
        facing_station="B",
        start_year=2025,
        end_year=2025,
        second_kld=True,
        network_source=network_path,
    )

    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "action": ACTION_MAINTAIN, "maintain_segments": ["A-B-LD"],
    }]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
    sim = result.simulator
    singela = next(s for s in sim.segments if s.name == "A-B")
    directional = next(s for s in sim.segments if s.name == "A-B-LD")
    assert directional.load_curva == 0.0  # reset
    assert singela.load_curva > 0.0  # untouched, kept its initial load
    assert sim.steps[-1]["maintained_segments"] == ["A-B-LD"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k maintain_segments_resets_only -v`
Expected: FAIL — `_handle_move_step` doesn't read `"maintain_segments"` yet, so `move_to` is called without it and resets both.

- [ ] **Step 3: Implement**

In `src/railroad_backend/services/manual_planner.py`, in `_handle_move_step`, replace:

```python
    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    try:
        simulator.move_to(segments, destination, action=action_code, duration_override=duration_override)
    except (RuntimeError, TypeError, ValueError) as exc:
```

with:

```python
    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    maintain_segment_names = step.get("maintain_segments")
    maintain_segments = (
        tuple(s for s in segments if s.name in maintain_segment_names)
        if maintain_segment_names is not None
        else None
    )
    try:
        simulator.move_to(segments, destination, action=action_code, duration_override=duration_override, maintain_segments=maintain_segments)
    except (RuntimeError, TypeError, ValueError) as exc:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k maintain_segments -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`

```bash
git add src/railroad_backend/services/manual_planner.py tests/test_integration.py
git commit -m "feat: manual plan replay threads maintain_segments through to move_to"
```

---

### Task 3: Manual Route "Add move" form exposes the choice

**Files:**
- Modify: `src/railroad_frontend/views/manual.py` (the "Add move" form, currently lines ~448-482)
- Test: manual verification via the running app (see Task 4) — this task has no new automated UI test; `streamlit.testing.v1.AppTest` cannot drive `st.radio` selection reliably enough within this form's conditional-rendering flow to be worth the brittleness (same call made for the Days-override form interactions earlier in this project). The `_handle_move_step`/`move_to` behavior is already covered by Tasks 1-2; this task is presentation-only.

**Interfaces:**
- Consumes: `ManualMoveOption.segments: Tuple[str, ...]` (existing).
- Produces: when `len(selected_option.segments) == 2` and `action_choice != "Move"`, a new `st.radio` lets the user pick "Ambos" / the Singela's name / the directional leg's name; the constructed step dict gains `"maintain_segments": [chosen_name]` when a single leg was chosen.

- [ ] **Step 1: Implement**

In `src/railroad_frontend/views/manual.py`, inside the `with st.form("manual_move_form", clear_on_submit=True):` block, after the existing `action_choice = st.radio(...)` and before `submitted_move = st.form_submit_button("Add move")`, insert:

```python
                maintain_choice = None
                if len(selected_option.segments) == 2 and action_choice != "Move":
                    singela_name, directional_name = selected_option.segments
                    maintain_choice = st.radio(
                        "Manutenção",
                        ("Ambos", f"Só a Singela ({singela_name})", f"Só o pátio ({directional_name})"),
                        horizontal=True,
                        help="Se a Singela já foi feita numa passada anterior, escolha só o pátio (ou vice-versa).",
                    )
```

Then, in the `if submitted_move:` block, replace:

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

with:

```python
                new_step = {
                    "mode": "move",
                    "segments": list(selected_option.segments),
                    "destination": selected_option.destination,
                    "action": action_code,
                }
                if maintain_choice and maintain_choice != "Ambos":
                    singela_name, directional_name = selected_option.segments
                    chosen_name = singela_name if maintain_choice.startswith("Só a Singela") else directional_name
                    new_step["maintain_segments"] = [chosen_name]
                new_plan = plan + [new_step]
```

- [ ] **Step 2: Run the full suite (no new tests in this task, must stay green) and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`

```bash
git add src/railroad_frontend/views/manual.py
git commit -m "feat: Manual Route Add-move form lets you maintain only the Singela or only the patio leg"
```

---

### Task 4: CHANGELOG and restart the running app

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add an entry under `[Unreleased]` / `### Added`**

```
- Manual Route: ao adicionar um passo de Manutenção/Só curvas num trecho
  com Singela + LP/LD, dá pra escolher manter só a Singela, só o pátio
  (LP/LD), ou os dois — útil quando um dos dois já foi esmerilhado numa
  passada anterior e não precisa repetir. Auto Simulation não muda.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for partial corridor maintenance"
```

- [ ] **Step 3: Restart the Streamlit process**

```bash
# stop the process bound to port 8501, then:
.venv\Scripts\python.exe run_streamlit.py
```

Verify: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/_stcore/health` returns `200`.
