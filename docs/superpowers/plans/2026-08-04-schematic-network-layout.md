# Schematic Network Layout from Pasted GPS Coordinates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user paste `NAME, LAT, LONG` lines for a network's stations and get a schematic layout — real relative direction preserved, edge spacing normalized — merged into the existing Network Editor X/Y override table.

**Architecture:** Three new pure functions in the domain layer (geographic projection, tree-diameter endpoints, BFS schematic placement), one new pure parsing function, and a UI section wired into the existing `_render_network_layout_controls` in `streamlit_app.py`. No new files — this composes with the layout-table mechanism already in place (fixed earlier: form-wrapped `st.data_editor`, `prefs["table_overrides"]`).

**Tech Stack:** Python, Streamlit, existing `railroad_backend.domain.network_layout` / `network_editor` modules, pytest, `streamlit.testing.v1.AppTest`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-schematic-network-layout-design.md`.
- Never commit without explicit user request (standing rule for this session — stage/verify only unless told otherwise).
- Run `.venv/Scripts/python.exe -m pytest tests/ -q` after every task; must stay green (currently 108 passing) before moving to the next task.
- Follow the project's commit prefixes (`feat:`, `fix:`, `test:`) if/when commits happen — see `CLAUDE.md` "Git — regras específicas deste projeto".
- Angle computation uses plain 2D `atan2`, NOT geographic/great-circle bearing (spec note, to avoid ambiguity).
- `SPACING` default is `1.0` — matches the existing per-station fallback spacing already used in `_render_network_layout_controls` (`coords = {"x": float(idx), "y": 0.0}`), resolving the spec's open question.

---

### Task 1: `project_geographic_coordinates`

**Files:**
- Modify: `src/railroad_backend/domain/network_layout.py`
- Test: `tests/test_network_layout.py`

**Interfaces:**
- Produces: `project_geographic_coordinates(coordinates: Mapping[str, Tuple[float, float]]) -> Dict[str, Tuple[float, float]]` — input `{name: (lat, long)}`, output `{name: (x, y)}` in local planar units. `{}` in, `{}` out.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_network_layout.py`:

```python
from railroad_backend.domain.network_layout import project_geographic_coordinates


def test_project_geographic_coordinates_orders_east_west_and_north_south():
    coords = {
        "A": (-20.0, -50.0),  # further north (less negative lat), further west
        "B": (-21.0, -49.0),  # further south, further east
    }
    projected = project_geographic_coordinates(coords)
    assert projected["A"][1] > projected["B"][1]  # A further north -> larger y
    assert projected["A"][0] < projected["B"][0]  # A further west -> smaller x


def test_project_geographic_coordinates_empty():
    assert project_geographic_coordinates({}) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -k project_geographic -v`
Expected: FAIL with `ImportError: cannot import name 'project_geographic_coordinates'`

- [ ] **Step 3: Write minimal implementation**

In `src/railroad_backend/domain/network_layout.py`, add `import math` to the top imports (alongside the existing `from typing import ...` line), then add this function after `_normalize_positions`:

```python
def project_geographic_coordinates(
    coordinates: Mapping[str, Tuple[float, float]]
) -> Dict[str, Tuple[float, float]]:
    """Project {name: (lat, long)} to local planar {name: (x, y)}.

    Equirectangular approximation (x = long * cos(mean_latitude), y = lat),
    adequate at a regional scale (a single rail corridor, not a global map).
    Compresses east-west distance by the mean latitude's cosine so stations
    at higher latitude don't get visually stretched east-west.
    """
    if not coordinates:
        return {}
    mean_lat_rad = math.radians(
        sum(lat for lat, _lon in coordinates.values()) / len(coordinates)
    )
    scale = math.cos(mean_lat_rad)
    return {
        name: (lon * scale, lat)
        for name, (lat, lon) in coordinates.items()
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -k project_geographic -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/domain/network_layout.py tests/test_network_layout.py
git commit -m "feat: add project_geographic_coordinates for schematic network layout"
```

---

### Task 2: `graph_diameter_endpoints`

**Files:**
- Modify: `src/railroad_backend/domain/network_layout.py`
- Test: `tests/test_network_layout.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `graph_diameter_endpoints(adjacency: Mapping[str, Sequence[str]]) -> Tuple[str, str]` — two station names that are endpoints of a longest shortest-path in the graph (double-BFS; assumes `adjacency` is connected — the real network is a single tree with no isolated stations). Used by Task 3 to pick where the schematic layout starts.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_network_layout.py`:

```python
from railroad_backend.domain.network_layout import graph_diameter_endpoints


def test_graph_diameter_endpoints_finds_unique_longest_path():
    # Trunk A-B-C-D-E-F (length 5) with a short branch C-G (max length 4
    # via G-C-D-E-F), so A-F is the unique longest path - no ties to worry
    # about in this test.
    adjacency = {
        "A": ["B"],
        "B": ["A", "C"],
        "C": ["B", "D", "G"],
        "D": ["C", "E"],
        "E": ["D", "F"],
        "F": ["E"],
        "G": ["C"],
    }
    a, b = graph_diameter_endpoints(adjacency)
    assert {a, b} == {"A", "F"}


def test_graph_diameter_endpoints_on_two_node_graph():
    adjacency = {"A": ["B"], "B": ["A"]}
    a, b = graph_diameter_endpoints(adjacency)
    assert {a, b} == {"A", "B"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -k graph_diameter -v`
Expected: FAIL with `ImportError: cannot import name 'graph_diameter_endpoints'`

- [ ] **Step 3: Write minimal implementation**

In `src/railroad_backend/domain/network_layout.py`, add `from collections import deque` to the top imports, then add this function after `project_geographic_coordinates`:

```python
def graph_diameter_endpoints(adjacency: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    """Return two station names at opposite ends of a longest shortest-path.

    Uses the standard double-BFS technique (correct for trees, a good-enough
    heuristic otherwise): BFS from any node finds one diameter endpoint;
    BFS from that endpoint finds the other. Assumes `adjacency` represents a
    connected graph rooted at one of its own keys.
    """

    def farthest_from(start: str) -> str:
        visited = {start: 0}
        queue = deque([start])
        farthest = start
        while queue:
            node = queue.popleft()
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    visited[neighbor] = visited[node] + 1
                    if visited[neighbor] > visited[farthest]:
                        farthest = neighbor
                    queue.append(neighbor)
        return farthest

    start = next(iter(adjacency))
    first_endpoint = farthest_from(start)
    second_endpoint = farthest_from(first_endpoint)
    return first_endpoint, second_endpoint
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -k graph_diameter -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/domain/network_layout.py tests/test_network_layout.py
git commit -m "feat: add graph_diameter_endpoints via double-BFS"
```

---

### Task 3: `schematic_layout_from_seed`

**Files:**
- Modify: `src/railroad_backend/domain/network_layout.py`
- Test: `tests/test_network_layout.py`

**Interfaces:**
- Consumes: `graph_diameter_endpoints(adjacency) -> Tuple[str, str]` from Task 2.
- Produces: `schematic_layout_from_seed(adjacency: Mapping[str, Sequence[str]], seed_positions: Mapping[str, Tuple[float, float]], *, spacing: float = 1.0) -> Dict[str, Tuple[float, float]]`. Only stations present in BOTH `adjacency` and `seed_positions` (and reachable from the diameter root through other seeded stations) get a result — this is how "station without GPS data" degrades gracefully per the spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_network_layout.py`:

```python
import math

from railroad_backend.domain.network_layout import schematic_layout_from_seed


def test_schematic_layout_from_seed_preserves_direction_normalizes_length():
    adjacency = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}
    # B is due east of A (same y); C is due north of B (same x as B).
    seed = {"A": (0.0, 0.0), "B": (10.0, 0.0), "C": (10.0, 10.0)}
    result = schematic_layout_from_seed(adjacency, seed, spacing=2.0)

    assert set(result) == {"A", "B", "C"}
    ax, ay = result["A"]
    bx, by = result["B"]
    cx, cy = result["C"]

    # A -> B direction preserved (east): B east of A, same y.
    assert bx > ax
    assert math.isclose(by, ay, abs_tol=1e-9)
    # B -> C direction preserved (north): C north of B, same x as B.
    assert math.isclose(cx, bx, abs_tol=1e-9)
    assert cy > by
    # Spacing normalized: both edges have length == spacing, regardless of
    # the seed's real (10-unit) distances.
    assert math.isclose(math.hypot(bx - ax, by - ay), 2.0, abs_tol=1e-9)
    assert math.isclose(math.hypot(cx - bx, cy - by), 2.0, abs_tol=1e-9)


def test_schematic_layout_from_seed_skips_stations_without_seed_data():
    adjacency = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}
    seed = {"A": (0.0, 0.0), "B": (10.0, 0.0)}  # C has no seed data
    result = schematic_layout_from_seed(adjacency, seed, spacing=1.0)
    assert set(result) == {"A", "B"}


def test_schematic_layout_from_seed_empty_seed_returns_empty():
    assert schematic_layout_from_seed({"A": ["B"]}, {}, spacing=1.0) == {}


def test_schematic_layout_from_seed_branch_point_fans_out_children():
    # B connects to A, C, and D - a branch point, like ZIQ in the real network.
    adjacency = {"A": ["B"], "B": ["A", "C", "D"], "C": ["B"], "D": ["B"]}
    seed = {
        "A": (0.0, 0.0),
        "B": (10.0, 0.0),   # east of A
        "C": (10.0, 10.0),  # north of B
        "D": (20.0, 0.0),   # east of B
    }
    result = schematic_layout_from_seed(adjacency, seed, spacing=1.0)
    assert set(result) == {"A", "B", "C", "D"}
    bx, by = result["B"]
    cx, cy = result["C"]
    dx, dy = result["D"]
    assert math.isclose(cx, bx, abs_tol=1e-9) and cy > by  # C stays north of B
    assert dx > bx and math.isclose(dy, by, abs_tol=1e-9)  # D stays east of B
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -k schematic_layout -v`
Expected: FAIL with `ImportError: cannot import name 'schematic_layout_from_seed'`

- [ ] **Step 3: Write minimal implementation**

In `src/railroad_backend/domain/network_layout.py`, add this function after `graph_diameter_endpoints`:

```python
def schematic_layout_from_seed(
    adjacency: Mapping[str, Sequence[str]],
    seed_positions: Mapping[str, Tuple[float, float]],
    *,
    spacing: float = 1.0,
) -> Dict[str, Tuple[float, float]]:
    """BFS layout that keeps each edge's real direction (from `seed_positions`)
    but normalizes every edge to the same `spacing` length.

    Only stations present in `seed_positions` participate; the walk never
    crosses into a station lacking seed data, so those are simply absent
    from the result (caller merges this over an existing layout - see
    `_render_network_layout_controls` in streamlit_app.py).
    """
    seeded = set(seed_positions)
    sub_adjacency: Dict[str, List[str]] = {
        name: [n for n in neighbors if n in seeded]
        for name, neighbors in adjacency.items()
        if name in seeded
    }
    if not sub_adjacency:
        return {}

    root, _ = graph_diameter_endpoints(sub_adjacency)
    positions: Dict[str, Tuple[float, float]] = {root: (0.0, 0.0)}
    visited = {root}
    queue = deque([root])
    while queue:
        current = queue.popleft()
        cx, cy = positions[current]
        sx, sy = seed_positions[current]
        for neighbor in sub_adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            nx_seed, ny_seed = seed_positions[neighbor]
            angle = math.atan2(ny_seed - sy, nx_seed - sx)
            positions[neighbor] = (
                cx + math.cos(angle) * spacing,
                cy + math.sin(angle) * spacing,
            )
            queue.append(neighbor)
    return positions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_layout.py -v`
Expected: PASS (all tests in the file, including Tasks 1-3's)

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/domain/network_layout.py tests/test_network_layout.py
git commit -m "feat: add schematic_layout_from_seed for direction-preserving station placement"
```

---

### Task 4: `parse_station_coordinates`

**Files:**
- Modify: `src/railroad_backend/domain/network_editor.py`
- Test: `tests/test_network_editor.py`

**Interfaces:**
- Produces: `parse_station_coordinates(text: str) -> Tuple[Dict[str, Tuple[float, float]], List[str]]` — `(parsed, messages)`. `parsed` maps station name -> `(lat, long)`. `messages` lists one human-readable string per skipped/invalid line (malformed line, non-numeric value, duplicate name). Never raises on bad input — every problem becomes a message and the line is skipped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_network_editor.py`:

```python
from railroad_backend.domain.network_editor import parse_station_coordinates


def test_parse_station_coordinates_comma_separated():
    text = "RDA, -15.55, -54.56\nTRO, -16.70, -54.67"
    parsed, messages = parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.55, -54.56), "TRO": (-16.70, -54.67)}
    assert messages == []


def test_parse_station_coordinates_tab_separated():
    text = "RDA\t-15.55\t-54.56"
    parsed, messages = parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.55, -54.56)}
    assert messages == []


def test_parse_station_coordinates_skips_blank_lines():
    text = "RDA, -15.55, -54.56\n\n   \nTRO, -16.70, -54.67"
    parsed, messages = parse_station_coordinates(text)
    assert set(parsed) == {"RDA", "TRO"}
    assert messages == []


def test_parse_station_coordinates_reports_malformed_line():
    text = "RDA, -15.55, -54.56\nBADLINE\nTRO, -16.70, -54.67"
    parsed, messages = parse_station_coordinates(text)
    assert set(parsed) == {"RDA", "TRO"}
    assert len(messages) == 1
    assert "Line 2" in messages[0]


def test_parse_station_coordinates_reports_non_numeric():
    text = "RDA, abc, -54.56"
    parsed, messages = parse_station_coordinates(text)
    assert parsed == {}
    assert len(messages) == 1
    assert "Line 1" in messages[0]


def test_parse_station_coordinates_reports_duplicate_and_keeps_last():
    text = "RDA, -15.55, -54.56\nRDA, -15.99, -54.99"
    parsed, messages = parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.99, -54.99)}
    assert len(messages) == 1
    assert "duplicate" in messages[0].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_editor.py -k parse_station_coordinates -v`
Expected: FAIL with `ImportError: cannot import name 'parse_station_coordinates'`

- [ ] **Step 3: Write minimal implementation**

In `src/railroad_backend/domain/network_editor.py`, add this function after `parse_spur_text` (it already imports `re` and the needed `typing` names at the top of the file):

```python
def parse_station_coordinates(text: str) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    """Parse pasted 'NAME, LAT, LONG' (comma- or tab-separated) lines.

    Returns (parsed, messages): parsed maps station name -> (lat, long);
    messages lists one human-readable warning per skipped/invalid line.
    Never raises - bad input becomes a message, not an exception. Duplicate
    station names: the later line wins, with a warning.
    """
    parsed: Dict[str, Tuple[float, float]] = {}
    messages: List[str] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[,\t]+", line) if p.strip()]
        if len(parts) != 3:
            messages.append(
                f"Line {line_no}: expected 'NAME, LAT, LONG', got {len(parts)} field(s) - skipped."
            )
            continue
        name, lat_raw, lon_raw = parts
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            messages.append(
                f"Line {line_no}: '{lat_raw}' / '{lon_raw}' is not numeric - skipped."
            )
            continue
        if name in parsed:
            messages.append(f"Line {line_no}: duplicate station '{name}' - using the later value.")
        parsed[name] = (lat, lon)
    return parsed, messages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_editor.py -k parse_station_coordinates -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/railroad_backend/domain/network_editor.py tests/test_network_editor.py
git commit -m "feat: add parse_station_coordinates for pasted GPS lists"
```

---

### Task 5: Wire GPS import into the Network Editor UI

**Files:**
- Modify: `streamlit_app.py`
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `project_geographic_coordinates` (Task 1), `schematic_layout_from_seed` (Task 3), `parse_station_coordinates` (Task 4), and the existing `build_adjacency_map` (already in `railroad_backend.domain.network_layout`, currently unused in `streamlit_app.py`).
- Produces: nothing new for later tasks — this is the UI integration point.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_streamlit_app_ui.py` (reuses the `_open_network_editor` helper already defined there):

```python
def test_gps_import_computes_schematic_positions_and_leaves_other_stations_untouched(
    tmp_path: Path,
) -> None:
    at = _open_network_editor(tmp_path)

    # C already has a manual override before the import - it must survive
    # untouched, since the pasted list below only covers A and B.
    state = at.session_state["network_editor_state"]
    state["layout_settings"]["table_overrides"]["C"] = {"x": 42.0, "y": 42.0}

    at.session_state["network_layout_gps_text"] = (
        "A, 0.0, 0.0\n"
        "B, 0.0, 1.0\n"  # B due east of A (longitude increases east)
    )
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    assert len(import_buttons) == 1
    import_buttons[0].click().run()
    assert not at.exception

    state = at.session_state["network_editor_state"]
    overrides = state["layout_settings"]["table_overrides"]
    assert set(overrides) == {"A", "B", "C"}
    assert state["dirty"] is True

    ax, ay = overrides["A"]["x"], overrides["A"]["y"]
    bx, by = overrides["B"]["x"], overrides["B"]["y"]
    assert bx > ax  # B stays east of A
    assert overrides["C"] == {"x": 42.0, "y": 42.0}  # untouched - not in the pasted text


def test_gps_import_reports_unknown_station(tmp_path: Path) -> None:
    at = _open_network_editor(tmp_path)

    at.session_state["network_layout_gps_text"] = "NOPE, 0.0, 0.0"
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    import_buttons[0].click().run()
    assert not at.exception

    warnings = [w.value for w in at.warning]
    assert any("NOPE" in w for w in warnings)
    state = at.session_state["network_editor_state"]
    assert state["layout_settings"]["table_overrides"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k gps_import -v`
Expected: FAIL — `AssertionError: assert 0 == 1` (no button with that label exists yet) or similar, since the button doesn't exist.

- [ ] **Step 3: Write minimal implementation**

In `streamlit_app.py`, extend the import on line 95 to:

```python
from railroad_backend.domain.network_layout import (
    automatic_layout_positions,
    automatic_station_layout,
    build_adjacency_map,
    project_geographic_coordinates,
    schematic_layout_from_seed,
)
```

And extend the import block starting at line 97 to also bring in `parse_station_coordinates`:

```python
from railroad_backend.domain.network_editor import (
    network_editor_segment_df,
    network_editor_station_df,
    parse_station_coordinates,
    spur_rows_from_text,
    unique_network_path,
)
```

Then in `_render_network_layout_controls`, insert this block right after the line `overrides = prefs.get("table_overrides", {}) or {}` (currently line 575) and before `rows = []`:

```python
        with st.expander("📍 Importar coordenadas GPS", expanded=False):
            st.caption(
                "Cole uma linha por estação: NOME, LATITUDE, LONGITUDE "
                "(vírgula ou tab, direto do Excel). O sistema preserva a "
                "direção real entre estações vizinhas mas normaliza o "
                "espaçamento entre elas."
            )
            gps_text = st.text_area(
                "Coordenadas GPS", key="network_layout_gps_text", height=150
            )
            if st.button("Aplicar e normalizar posições", key="network_layout_gps_apply"):
                parsed, parse_messages = parse_station_coordinates(gps_text)
                station_set = set(state["stations_df"]["Name"].astype(str).tolist())
                unknown = sorted(set(parsed) - station_set)
                usable = {name: coords for name, coords in parsed.items() if name in station_set}
                for msg in parse_messages:
                    st.warning(msg)
                if unknown:
                    st.warning(
                        f"Estação(ões) não encontrada(s) na rede, ignorada(s): {', '.join(unknown)}."
                    )
                if usable:
                    projected = project_geographic_coordinates(usable)
                    schematic = schematic_layout_from_seed(
                        build_adjacency_map(config.segments),
                        projected,
                        spacing=1.0,
                    )
                    if schematic:
                        merged_overrides = dict(overrides)
                        merged_overrides.update(
                            {name: {"x": x, "y": y} for name, (x, y) in schematic.items()}
                        )
                        prefs["table_overrides"] = merged_overrides
                        overrides = merged_overrides
                        state["dirty"] = True
                        st.session_state.pop("network_layout_editor", None)
                        st.success(f"{len(schematic)} estação(ões) reposicionada(s).")
                    else:
                        st.warning("Nenhuma estação com dados suficientes para calcular posição.")
                elif not unknown:
                    st.warning("Nenhuma coordenada válida encontrada no texto colado.")

```

Note: `overrides` is reassigned to `merged_overrides` so the `rows`-building loop immediately below (unchanged) picks up the freshly computed positions in the same rerun, without needing a second interaction. `st.session_state.pop("network_layout_editor", None)` clears the X/Y table widget's own edit buffer so it re-seeds cleanly from the new `overrides` instead of potentially overlaying stale in-progress edits on top of the import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS (all tests in the file, including the two new ones and the earlier layout-table regression tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, 124 passed (108 before this plan + 2 from Task 1 + 2 from Task 2 + 4 from Task 3 + 6 from Task 4 + 2 from Task 5), no crash. If the count differs, that's fine as long as it's "N passed" with zero failures - the exact number only matters as a sanity check that nothing silently got skipped.

- [ ] **Step 6: Commit**

```bash
git add streamlit_app.py tests/test_streamlit_app_ui.py
git commit -m "feat: wire GPS coordinate import into Network Editor layout controls"
```

---

### Task 6: End-to-end verification with the real "Rumo - Nós" network

This task has no new production code — it verifies the feature against Bruno's actual data before calling the plan done, the same way the two bugs earlier in this session were verified against the real network file rather than only synthetic fixtures.

**Files:**
- None modified. Uses `data/networks/network_20251223_115340.json` (the "Rumo - Nós" network) read-only.

- [ ] **Step 1: Run a manual AppTest script against the real network**

Create a scratch script (not committed — delete after use, e.g. in the OS temp dir) that:
1. Opens the Network Editor page against `data/networks/network_20251223_115340.json`.
2. Pastes the 22-station GPS list (from the "Estação" sheet of `Nós.xlsx`, already transcribed earlier in this conversation):
   ```
   RDA, -15.55204687, -54.55858631
   TRO, -16.697259, -54.666807
   TAG, -17.249603, -53.311841
   TCS, -18.76453274, -52.699853
   TMI, -20.098625, -50.991482
   ZEB, -20.691028, -49.650608
   ZCZ, -21.323594, -48.602863
   ZTO, -21.7561105, -48.131572
   ZTI, -21.896336, -48.013043
   ZIQ, -22.2593943, -47.8180197
   ZTP, -22.3076779, -49.0456714
   ZQX, -22.362953, -47.655997
   ZRX, -22.447835, -47.56215
   ZRC, -22.768751, -47.301206
   ZBL, -22.908174, -47.140971
   ZKE, -23.575436, -47.167418
   ZEV, -23.900791, -46.747713
   ZPT, -23.979488, -46.508703
   ZPG, -23.877315, -46.409198
   PIT, -19.662375, -50.342742
   PSS, -19.06795, -50.525988
   PSG, -17.831616, -50.642908
   ```
3. Clicks "Aplicar e normalizar posições".
4. Asserts `at.session_state["network_editor_state"]["layout_settings"]["table_overrides"]` has all 22 station keys, no exception was raised, and no unknown-station warning fired (all 22 names must match the network's actual station names exactly).
5. Prints the resulting positions.

- [ ] **Step 2: Visually sanity-check the result**

With the dev server running (`nohup .venv/Scripts/python.exe -m streamlit run streamlit_app.py --server.headless true --server.fileWatcherType none`, matching how it's been run throughout this session), open the Network Editor for "Rumo - Nós", paste the same GPS list into the new "📍 Importar coordenadas GPS" box, click "Aplicar e normalizar posições", and check the sketch expander: the shape should read as a single branching corridor running roughly from the upper-left (RDA/TRO, Mato Grosso) toward the lower-right (ZPT/ZPG/ZEV, São Paulo coast) — not the zigzag from the original bug report — with the TMI→PIT→PSS→PSG and ZIQ→ZTP spurs visibly branching off at their real relative angle.

- [ ] **Step 3: Report back**

Summarize to Bruno: confirm the import worked end-to-end on the real network, note anything about the resulting shape that looks off (this is exploratory — the algorithm is deterministic and tested, but a real 22-station tree may reveal a rough edge synthetic tests didn't, e.g. two branches whose real-world angles are close enough to visually overlap in the schematic version). No further tasks unless Bruno asks for a follow-up.

---

## Spec sections NOT covered here (by design)

The "singela splits into LP/LD and rejoins" segment-rendering redesign (spec's "Non-goals" section) is intentionally out of scope for this plan — it was deferred to a follow-up design in the brainstorming session, to be brainstormed separately once this layout foundation is in place and verified.
