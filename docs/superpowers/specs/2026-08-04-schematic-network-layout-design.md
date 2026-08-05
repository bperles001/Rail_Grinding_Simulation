# Schematic network layout from pasted GPS coordinates

Date: 2026-08-04
Status: Approved, ready for implementation plan

## Problem

The Network Editor's sketch (`_network_figure` in `streamlit_app.py`, backed by
`automatic_layout_positions` in `src/railroad_backend/domain/network_layout.py`)
positions stations using purely topological algorithms (`planar_layout`,
`kamada_kawai_layout`, `spring_layout`). These have no notion of real-world
geography, so on a large network (the "Rumo - Nós" network: 22 stations, a
single branching corridor with no cycles) the result is an illegible zigzag
with no relationship to the actual shape of the railway.

The existing manual fallback — the per-station X/Y override table in the
"🗺️ Network sketch & layout" expander — lets a user fix this by hand, but
populating it cell-by-cell for 22+ stations is impractical.

The user has real GPS coordinates (latitude/longitude) for every station in
this network, sourced from an external spreadsheet (`Nós.xlsx`, "Estação"
sheet). Using them directly (as raw X=longitude, Y=latitude) is not desirable
either: real inter-station distances vary enormously (some segments are very
short), so a directly-proportional plot would cramp short segments into
illegibility next to long ones.

## Goal

Let the user paste a list of `STATION, LATITUDE, LONGITUDE` and get a
**schematic** layout: same general geographic shape/direction as the real
map, but with roughly uniform spacing between connected stations — the same
visual convention used by metro/rail diagrams.

## Non-goals (explicitly out of scope for this design)

- Redrawing parallel segments (Singela/LP/LD or Singela/Carregado/Vazio) as
  diverging/reconverging curves (the user's second reference sketch). That is
  a separate follow-up design; it depends on stations already being
  well-positioned, which is what this design delivers.
- Handling networks with cycles gracefully is a soft requirement (see
  Algorithm, "Non-tree edges") but not a primary target — the current real
  network is a pure tree (trunk + 2 spurs, no loops).
- Auto-detecting/importing GPS data from the `Nós.xlsx` file automatically.
  The user pastes the text manually; no filesystem access to that external
  spreadsheet is wired into the app.

## Data flow

```
User pastes "NAME, LAT, LONG" lines
        │
        ▼
Parse into {name: (lat, long)}          [new: parse_station_coordinates()]
        │
        ▼
Project lat/long -> local planar X/Y     [new: project_geographic_coordinates()]
(equirectangular, longitude scaled by cos(mean_latitude))
        │
        ▼
Build adjacency from current segments    [existing: build_adjacency_map()]
        │
        ▼
Schematic layout: BFS from a trunk        [new: schematic_layout_from_seed()]
endpoint, each edge keeps the seed's
real bearing but a uniform length
        │
        ▼
Result: {name: {"x": float, "y": float}}
        │
        ▼
Merged into `prefs["table_overrides"]`   (existing mechanism, same shape
                                           the X/Y table already reads/writes)
```

Stations present in the pasted text but absent from the network are reported
back to the user and skipped. Stations present in the network but absent from
the pasted text are left untouched (they keep whatever position they already
had — an existing override, or the current auto-layout fallback) so a partial
paste never breaks the sketch.

## Algorithm detail

**Why not a force-directed re-layout (spring/Kamada-Kawai) seeded with the
GPS positions?** It was considered, but on a sparse tree-shaped graph,
Fruchterman-Reingold-style relaxation is not reliably shape-preserving — its
final layout depends on iteration count and internal spring constants in a
way that's hard to predict or explain, and could still bend the corridor into
something unrecognizable. The network has no cycles, so a direct geometric
construction is both simpler and deterministic.

**Steps:**

1. **Project.** Convert each `(lat, long)` to local planar coordinates:
   `x = long * cos(mean_latitude_radians)`, `y = lat`. This is a standard,
   cheap equirectangular approximation, adequate at this regional scale (a
   Brazilian rail corridor, not a global map) and avoids east-west distortion
   at this latitude (~-20°, cos ≈ 0.94 — small but free to correct).
2. **Pick a root.** Find the two endpoints of the graph's diameter (longest
   shortest-path) via double-BFS on the adjacency map; use one endpoint as
   the root. This orients the schematic layout along the network's longest
   axis, matching how the trunk corridor should read.
3. **BFS placement.** Walk the spanning tree from the root breadth-first.
   Root gets `(0, 0)`. For each tree edge `parent -> child`: compute the
   plane angle `atan2(child_seed.y - parent_seed.y, child_seed.x - parent_seed.x)`
   between `parent`'s and `child`'s *projected* seed coordinates (from step 1
   — this is a flat 2D angle, not a geographic/great-circle bearing); place
   `child` at `parent_position + unit_vector(angle) * SPACING`, where `SPACING` is a
   fixed constant matching the existing auto-layout's normalized scale (so
   the schematic result is visually comparable to the "auto" layout mode,
   not zoomed wildly differently).
4. **Non-tree edges** (only relevant for a future network with a cycle):
   any segment whose stations are both already placed via different tree
   branches is simply not used to re-position anything — the station keeps
   its BFS-assigned position. No special handling; this only means a cycle
   wouldn't visually "close up" against the schematic edge, which is an
   acceptable, documented limitation given the current network has none.
5. **Unreached stations** (disconnected from the root's component, e.g. a
   station with no segments yet): keep existing behavior — fall back to
   whatever `automatic_station_layout`/table default already assigns them.

## UI

In `_render_network_layout_controls` (`streamlit_app.py`), inside the
existing `mode == "table"` branch, add above the X/Y `st.data_editor`:

- A `st.text_area` ("Colar coordenadas GPS") accepting one station per line,
  fields separated by comma or tab (so a direct paste from Excel columns
  works without reformatting).
- A button, "Aplicar e normalizar posições" (plain `st.button`, not inside
  the layout form — this is a single explicit action, not a multi-cell grid,
  so it doesn't have the self-feeding-baseline problem the X/Y table had).
- On click: parse -> project -> schematic-layout -> merge results into
  `prefs["table_overrides"]` -> `state["dirty"] = True` -> rerun. The
  existing X/Y table (already fixed to use a form) then shows the computed
  values, and the user can hand-tune individual stations afterward exactly
  as today.
- Parse errors (malformed line, non-numeric lat/long) and unknown-station
  names are surfaced as a `st.warning`/`st.error` listing exactly which
  lines were skipped and why — never silently drop input.

## New code

| File | Addition |
|---|---|
| `src/railroad_backend/domain/network_layout.py` | `project_geographic_coordinates()`, `schematic_layout_from_seed()`, `graph_diameter_endpoints()` (or inline helper) |
| `src/railroad_backend/domain/network_editor.py` or a new small module | `parse_station_coordinates(text: str) -> tuple[dict[str, tuple[float,float]], list[str]]` (parsed rows + list of error/skip messages) |
| `streamlit_app.py` | UI wiring in `_render_network_layout_controls` |

## Testing

- Unit tests for `parse_station_coordinates`: comma vs tab separated, blank
  lines, malformed rows, duplicate station names.
- Unit tests for `project_geographic_coordinates`: known lat/long pairs ->
  expected relative ordering (station further east has larger X, etc).
- Unit tests for `schematic_layout_from_seed` using a small synthetic tree
  (a trunk + one branch, mirroring the real network's shape) asserting: (a)
  every station gets a distinct position, (b) edge lengths in the result are
  uniform within a tolerance, (c) the relative angular ordering of a branch's
  children matches the seed data's ordering.
- One `AppTest`-based UI test (matching the pattern in
  `tests/test_streamlit_app_ui.py`) pasting a small coordinate list, clicking
  "Aplicar e normalizar posições", and asserting `table_overrides` was
  populated for the pasted stations and left untouched for a station that
  was not in the pasted text.

## Open questions / assumptions carried into the plan

- `SPACING` constant: reuse whatever normalized scale
  `automatic_station_layout` already produces (that function normalizes
  positions to a `0..len(positions)` range) so the schematic and auto-layout
  results are on a comparable visual scale. The implementation plan should
  pick the exact value by inspecting that function's actual output range
  rather than guessing a new one.
