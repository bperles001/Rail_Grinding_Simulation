# Changelog

All notable changes to this project will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) |
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

<!-- Add new changes here as you work. Move to a versioned section when releasing. -->

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
