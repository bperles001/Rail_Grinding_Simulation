# Changelog

All notable changes to this project will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) |
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Added
- Segment now tracks `curve_length_km` / `tangent_length_km` (extensão em curva x
  tangente dentro do segmento) and `move_billed_days` / `maintenance_billed_days`
  (diárias pagas, distintas dos dias corridos) — novas colunas no Network Editor.
  Campos opcionais, com default 0.0, para não quebrar redes já salvas.
- Network Editor's layout controls now have a "📍 Importar coordenadas GPS" box:
  paste `NOME, LATITUDE, LONGITUDE` lines (one per station) and click "Aplicar
  e normalizar posições" to get a schematic layout — real relative direction
  between connected stations preserved, edge spacing normalized to a uniform
  value (same convention as metro/rail diagrams), instead of the purely
  topological auto-layout that produced illegible zigzags on larger networks.
  New pure functions: `project_geographic_coordinates`,
  `graph_diameter_endpoints`, `schematic_layout_from_seed`
  (`src/railroad_backend/domain/network_layout.py`) and
  `parse_station_coordinates` (`src/railroad_backend/domain/network_editor.py`).
  Design: `docs/superpowers/specs/2026-08-04-schematic-network-layout-design.md`.

### Fixed
- **Critical**: selecting a network with enough stations/segments (~20+/~40+)
  would hang the app indefinitely (multi-minute, CPU-pegged, no error shown).
  Root cause: `streamlit_app.py`'s `_update_schedule_network_warnings()` passed
  `Segment` objects (not names) to `schedule_missing_segments()`, which calls
  `str()` on each — and since `Station`/`Segment` hold circular references to
  each other (`Station.segments` ↔ `Segment.start_station`/`end_station`), the
  default dataclass `__repr__` recursed through the whole graph with no
  memoization, causing combinatorial blowup. Small networks (13 stations)
  masked this; a real ~22-station network exposed it. Fixed the call site to
  pass segment names, and added explicit shallow `__repr__` to `Station` and
  `Segment` (`src/models/__init__.py`) so this class of bug can't recur via
  any other accidental `str()`/log/debug call on these objects.
- **Network Editor**: editing the layout X/Y override table a second time
  (before saving) used to silently drop both edits and reset the widget.
  Root cause: the table's `st.data_editor` lived outside a form and rebuilt
  its `data=` baseline from the very state its own edits had just written to,
  so each keystroke rerun fed the widget a "new" baseline that collapsed its
  pending edit buffer. Fixed by wrapping it in `st.form` with an explicit
  "Apply layout changes" button, matching the Stations/Segments editors
  elsewhere on the same page (they already used this pattern).
- Matplotlib now explicitly uses the `Agg` (headless) backend instead of
  relying on auto-selection, which could land on a GUI backend (`TkAgg` on
  this machine) unsafe to touch outside its owning thread.

---

## [0.5.0] — 2026-06-02

### Added
- Network editor with full station/segment CRUD and timeline order configuration
- MTBT editor for maintenance threshold management per segment/month
- Automatic simulation with greedy heuristic planner (`auto_planner.py`)
- Manual simulation with step-by-step route planning and plan save/load
- Results comparison page (automatic vs. manual side by side)
- Configurable timeline generation (Gantt-style matplotlib chart)
- Action constants `ACTION_MAINTAIN` / `ACTION_MOVE` in `src/models/__init__.py`
  replacing cryptic `"m"` / `"v"` string literals; legacy values still accepted
- Python `logging` module integrated in `simulator/core.py`, `auto_planner.py`,
  `manual_planner.py` — errors are now traceable instead of silent

### Architecture
- 3-layer architecture: `simulator/` (pure engine) → `railroad_backend/`
  (domain + services) → `railroad_frontend/` (Streamlit UI)
- Frozen dataclass callbacks pattern for Streamlit state management
- Session state keys as typed string constants in `state/session.py`
- `NetworkConfig` dataclass as the single parsed representation of a network JSON
- `VALID_ACTIONS` frozenset for input validation in `Simulator.move_to()`

### Fixed
- Broad `except Exception: pass` blocks replaced with specific `(TypeError, ValueError)`
  catches that log at DEBUG/WARNING level instead of silently discarding errors
