# Manual Route Days Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a single "Traverse" (move/maintenance) step in a Manual Route plan have its day-count overridden without changing the segment's base `move_time_days`/`maintenance_time_days`.

**Architecture:** Add an optional `days_override` key to move-mode plan step dicts; thread it through `Simulator.move_to()` as `duration_override`; wire the Manual Route table to display/edit it.

**Tech Stack:** Python 3.12, Streamlit `data_editor`, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-manual-route-days-override-design.md` is authoritative.
- Auto Simulation (`auto_planner.py`) must not change at all.
- Absence of `days_override` must reproduce today's exact behavior (no regression in the 136 existing tests).
- Run `.venv\Scripts\python.exe -m pytest -q` after every task; must stay green.
- Commit after each task.

---

### Task 1: `Simulator.move_to()` accepts `duration_override`

**Files:**
- Modify: `src/simulator/core.py` (`move_to`, currently starting at line 257; the `duration = seg.maintenance_time_days` / `duration = seg.move_time_days` assignments are at lines 325 and 330 per the current file)
- Test: `tests/test_edge_cases.py`

**Interfaces:**
- Produces: `Simulator.move_to(self, seg, next_station, action="v", duration_override: Optional[int] = None) -> Dict[str, object]`. When `duration_override` is not `None`, it replaces the computed `duration` in both the "performed" (maintenance) and "not performed" (move) branches; every other effect of `move_to` (MTBT load, maintenance flags, step dict's `action`/`facing`/`mtbt_before_*` fields) is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_edge_cases.py`:

```python
def test_move_to_duration_override_replaces_base_move_days():
    """duration_override should control the date advance instead of seg.move_time_days."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.move_time_days != 7  # sanity: override differs from the base fixture value
    before = sim.simulation_date
    sim.move_to(seg, seg.end_station, action="v", duration_override=7)
    assert (sim.simulation_date - before).days == 7
    assert sim.steps[-1]["days"] == 7


def test_move_to_duration_override_replaces_base_maintenance_days():
    """duration_override should also apply to the maintenance branch."""
    from src.models import ACTION_MAINTAIN

    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.maintenance_time_days != 11
    sim.machine.second_kld_installed = True  # force perform_maintenance regardless of direction
    before = sim.simulation_date
    sim.move_to(seg, seg.end_station, action=ACTION_MAINTAIN, duration_override=11)
    assert (sim.simulation_date - before).days == 11
    assert sim.steps[-1]["days"] == 11


def test_move_to_without_duration_override_uses_segment_base():
    """No override -> unchanged behavior, duration comes from the segment."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    before = sim.simulation_date
    sim.move_to(seg, seg.end_station, action="v")
    assert (sim.simulation_date - before).days == seg.move_time_days
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k duration_override -v`
Expected: FAIL — `move_to() got an unexpected keyword argument 'duration_override'`.

- [ ] **Step 3: Implement**

In `src/simulator/core.py`, change the signature:

```python
    def move_to(self, seg: Segment, next_station: Station, action: str = "v", duration_override: Optional[int] = None) -> Dict[str, object]:
```

(add `Optional` to the existing `typing` import at the top of the file if not already imported — check the current import line before editing).

Then change the two duration assignments:

```python
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_edge_cases.py -k duration_override -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 139 passed (136 + 3 new).

```bash
git add src/simulator/core.py tests/test_edge_cases.py
git commit -m "feat: Simulator.move_to accepts a per-call duration_override"
```

---

### Task 2: `_handle_move_step` threads `days_override` through

**Files:**
- Modify: `src/railroad_backend/services/manual_planner.py` (`_handle_move_step`, currently lines 149-180)
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: `Simulator.move_to(..., duration_override=...)` from Task 1.
- Produces: `_handle_move_step` reads `step.get("days_override")` and passes it as `duration_override`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py` near the other `replay_manual_plan` tests:

```python
def test_manual_plan_step_days_override_changes_duration(tmp_path):
    """A move step with days_override should advance the date by that many days."""
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

    result = replay_manual_plan(config, [])
    sim = result.simulator
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.move_time_days != 9

    plan = [{"mode": "move", "segment": seg.name, "destination": "TMI", "action": "v", "days_override": 9}]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
    assert result.simulator.steps[-1]["days"] == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k days_override -v`
Expected: FAIL — `steps[-1]["days"] == 5` (base), not 9.

- [ ] **Step 3: Implement**

In `src/railroad_backend/services/manual_planner.py`, in `_handle_move_step`, replace:

```python
    action_code = step.get("action", ACTION_MOVE)
    try:
        simulator.move_to(segment, destination, action=action_code)
    except (RuntimeError, TypeError, ValueError) as exc:
```

with:

```python
    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    try:
        simulator.move_to(segment, destination, action=action_code, duration_override=duration_override)
    except (RuntimeError, TypeError, ValueError) as exc:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -k days_override -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 140 passed.

```bash
git add src/railroad_backend/services/manual_planner.py tests/test_integration.py
git commit -m "feat: manual plan replay applies per-step days_override"
```

---

### Task 3: Manual Route table shows and edits Days for Traverse steps

**Files:**
- Modify: `src/railroad_frontend/views/manual.py` (`_manual_plan_dataframe` at line 517, and the edit-application loop at lines 258-276)
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `network_segments_provider()` (already a field on `ManualRouteCallbacks`, returns `Sequence[Segment]`).
- Produces: `_manual_plan_dataframe(plan, config, segments)` — new third positional parameter. All call sites of `_manual_plan_dataframe` inside `manual.py` must be updated to pass `callbacks.network_segments_provider()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_streamlit_app_ui.py` (following the existing `AppTest`-based pattern in that file — reuse `_open_network_editor`'s style of writing a network file and driving `streamlit_app.py`; if a simpler pure-function test is possible for `_manual_plan_dataframe`, prefer that — see Step 1a below for the pure-function version, which is faster and sufficient for this behavior):

```python
def test_manual_plan_dataframe_shows_segment_base_days_for_traverse():
    from streamlit_app import _manual_plan_dataframe  # re-exported from railroad_frontend.views.manual if needed — see note below
    from src.models import Segment, Station

    a = Station("A")
    b = Station("B")
    seg = Segment(name="A-B", start_station=a, end_station=b, length=1.0, move_time_days=3, maintenance_time_days=6)

    plan = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "v"}]
    df = _manual_plan_dataframe(plan, {}, [seg])
    assert df.loc[0, "Days"] == 3

    plan_maint = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "m"}]
    df_maint = _manual_plan_dataframe(plan_maint, {}, [seg])
    assert df_maint.loc[0, "Days"] == 6

    plan_override = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "v", "days_override": 9}]
    df_override = _manual_plan_dataframe(plan_override, {}, [seg])
    assert df_override.loc[0, "Days"] == 9
```

Note: `_manual_plan_dataframe` is a module-private function in
`src/railroad_frontend/views/manual.py`. Import it directly from there
instead of via `streamlit_app`:

```python
from railroad_frontend.views.manual import _manual_plan_dataframe
```

(replace the import line in the test above accordingly).

- [ ] **Step 1a: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -k manual_plan_dataframe -v`
Expected: FAIL — `_manual_plan_dataframe() missing 1 required positional argument: 'segments'` (once the signature is changed) or, before that, `Days` is `None` instead of `3`/`6`/`9` (current behavior). Run it now, before Step 2, against the *current* code to confirm it fails for the right reason (`None != 3`).

- [ ] **Step 2: Implement the dataframe change**

In `src/railroad_frontend/views/manual.py`, change the function signature and the Traverse branch (currently around line 517-565):

```python
def _manual_plan_dataframe(plan: List[Dict[str, Any]], config: Dict[str, Any], segments: Sequence[Any]) -> pd.DataFrame:
    if not plan:
        return pd.DataFrame(columns=["Step", "Type", "Segment", "Destination", "Action", "Days", "Capability"])
    second_kld = bool(config.get("second_kld", False))
    segments_by_name = {seg.name: seg for seg in segments}
    rows = []
    for idx, step in enumerate(plan, start=1):
        if step.get("mode") == "turn":
            rows.append({
                "Step": idx,
                "Type": "Turn",
                "Segment": "-",
                "Destination": "-",
                "Action": "—",
                "Days": None,
                "Capability": "Facing change",
            })
        elif step.get("mode") == "wait":
            wait_days = int(step.get("days", 1))
            rows.append({
                "Step": idx,
                "Type": "Wait",
                "Segment": "-",
                "Destination": "-",
                "Action": "—",
                "Days": wait_days,
                "Capability": "Hold position",
            })
        else:
            aligned = step.get("aligned")
            if aligned:
                capability = "Maintenance allowed"
            elif second_kld:
                capability = "Maintenance allowed (2nd KLD)"
            else:
                capability = "Move only"
            _act = step.get("action")
            is_maintenance = _act in ("m", "maintain", "maintain_curves")
            seg_obj = segments_by_name.get(step.get("segment"))
            if seg_obj is not None:
                base_days = seg_obj.maintenance_time_days if is_maintenance else seg_obj.move_time_days
            else:
                base_days = None
            days_value = step.get("days_override", base_days)
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
                "Days": days_value,
                "Capability": capability,
            })
    return pd.DataFrame(rows)
```

Update the call site (around line 216): `plan_df = _manual_plan_dataframe(plan, config)` becomes:

```python
    plan_df = _manual_plan_dataframe(plan, config, callbacks.network_segments_provider())
```

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -k manual_plan_dataframe -v`
Expected: PASS.

- [ ] **Step 4: Write the failing test for the edit-application loop**

Add to `tests/test_streamlit_app_ui.py`:

```python
def test_manual_route_days_edit_sets_override_for_traverse_step(tmp_path):
    """Editing the Days cell of a Traverse row in the Manual Route table should
    persist as days_override on that step (and only that step)."""
    network_path = tmp_path / "network.json"
    _write_network(network_path)  # existing helper in this file, 2-station network A-B

    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.session_state["active_network_path"] = str(network_path)
    at.session_state["navigation_page"] = "Manual Route"
    at.run()
    # Drive to a state with one Traverse step already in the plan, then edit its Days cell.
    # (Exact widget interaction depends on the app's existing move-add controls — reuse
    # whatever selectbox/button the Manual Route page already exposes for "add a move";
    # inspect `at.selectbox` / `at.button` keys via `at.get(...)` if the exact key is unknown.)
    ...
```

This test requires driving the real Streamlit app end-to-end and depends on
widget keys that aren't documented above — **before writing it for real**,
run:

```bash
.venv\Scripts\python.exe -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('streamlit_app.py', default_timeout=60)
at.run()
at.session_state['navigation_page'] = 'Manual Route'
at.run()
print([w.key for w in at.selectbox])
print([w.key for w in at.button])
"
```

to discover the actual selectbox/button keys for adding a move step, then
fill in the `...` above with real `at.selectbox(key=...).select(...)` /
`at.button(key=...).click()` calls before `at.run()`, followed by locating
the `plan_step_editor` data_editor and setting its `Days` value via
`at.data_editor(key="plan_step_editor").edit(...)` — consult the
`streamlit.testing.v1` docs (`AppTest`/`DeltaGenerator` element APIs) if the
edit method name differs from `.edit(...)` in the installed Streamlit
version (check with `.venv\Scripts\python.exe -m pip show streamlit`).

- [ ] **Step 5: Run test to verify it fails, then implement the edit-loop change**

In `src/railroad_frontend/views/manual.py`, the edit-application loop
(currently lines 258-276) gains a `move` branch. Replace:

```python
        # Apply changes made directly in the table
        _new_plan = list(plan)
        _changed = False
        for _i, _row in edited_df.iterrows():
            _step = _new_plan[_i]
            _mode = _step.get("mode")
            if _mode == "move":
                _new_code = _ACTION_MAP.get(str(_row.get("Action", "Move")), ACTION_MOVE)
                if _new_code != _step.get("action"):
                    _new_plan[_i] = {**_step, "action": _new_code}
                    _changed = True
            elif _mode == "wait":
```

with:

```python
        # Apply changes made directly in the table
        segments_by_name = {seg.name: seg for seg in callbacks.network_segments_provider()}
        _new_plan = list(plan)
        _changed = False
        for _i, _row in edited_df.iterrows():
            _step = _new_plan[_i]
            _mode = _step.get("mode")
            if _mode == "move":
                _new_code = _ACTION_MAP.get(str(_row.get("Action", "Move")), ACTION_MOVE)
                if _new_code != _step.get("action"):
                    _step = {**_step, "action": _new_code}
                    _new_plan[_i] = _step
                    _changed = True
                _is_maintenance = _step.get("action") in ("m", "maintain", "maintain_curves")
                _seg_obj = segments_by_name.get(_step.get("segment"))
                _base_days = (_seg_obj.maintenance_time_days if _is_maintenance else _seg_obj.move_time_days) if _seg_obj else None
                try:
                    _edited_days = int(_row.get("Days")) if _row.get("Days") is not None else _base_days
                except (TypeError, ValueError):
                    _edited_days = _base_days
                if _edited_days is not None and _edited_days != _base_days:
                    if _step.get("days_override") != _edited_days:
                        _new_plan[_i] = {**_step, "days_override": _edited_days}
                        _changed = True
                elif "days_override" in _step:
                    _step = {k: v for k, v in _step.items() if k != "days_override"}
                    _new_plan[_i] = _step
                    _changed = True
            elif _mode == "wait":
```

(the rest of the `elif _mode == "wait":` branch and everything after it stays
exactly as-is).

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS. If the `AppTest`-driven test from Step 4 proves too brittle
to finish within this task, it is acceptable to drop it and rely on the pure
`_manual_plan_dataframe` unit tests (Step 1) plus the backend tests (Tasks 1-2)
for coverage — note this explicitly in the commit message if so, since the
edit-loop's dict-manipulation logic has no other direct test otherwise.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests passed.

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: Manual Route table edits Days per-step for Traverse rows"
```

---

### Task 4: Update CHANGELOG and restart the running app

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add an entry under `[Unreleased]` / `### Added`**

```
- Manual Route plan steps can now override the day-count of a single
  move/maintenance step (`days_override`) without changing the segment's
  base `move_time_days`/`maintenance_time_days` — the Days cell in the plan
  table is editable for Traverse rows too, not just Wait rows. Auto
  Simulation is unaffected.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for Manual Route days override"
```

- [ ] **Step 3: Restart the Streamlit process**

```bash
# stop the process bound to port 8501, then:
.venv\Scripts\python.exe run_streamlit.py
```

Verify: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/_stcore/health` returns `200`.
