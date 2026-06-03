# Railroad Maintenance Simulator

## Overview
The Railroad Maintenance Simulator is now centered on a Streamlit dashboard that lets planners:

- Inspect the current MTBT schedule and a corridor-wide timeline
- Compare automatically generated plans with curated/manual adjustments
- Edit the MTBT CSV in-line and immediately apply it to the simulator
- Persist manual plans (`data/saved_plans.json`) for quick reloads
- Export the rendered timeline as a PNG for reports or email updates

The underlying simulator still models the grinder as a single machine that moves along the corridor with a persistent global direction and spur-specific rules (see **Global direction model** below).

> 📖 **For detailed architecture documentation**, including design principles, data flow diagrams, and extension points, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Project structure
```
railroad-maintenance-simulator/
├── streamlit_app.py            # Streamlit router wiring tabs + shared session helpers
├── src/
│   ├── __init__.py
│   ├── railroad_frontend/      # Components, modularized tabs, and session helpers
│   │   ├── components/
│   │   ├── state/
│   │   └── views/
│   ├── railroad_backend/       # Backend services and domain logic
│   │   ├── domain/             # Shared business logic (network_editor, network_layout, persistence, schedule)
│   │   ├── services/           # High-level planning services (auto_planner, manual_planner, network_editor, schedule_service)
│   │   └── persistence/        # Data storage (plan_storage)
│   ├── models/                 # Station, Segment, GrinderMachine
│   ├── simulator/              # Core simulation engine
│   └── utils/                  # MTBT transforms, timeline utilities, network loaders
├── data/
│   ├── mtbt_schedule.csv       # Authoritative MTBT schedule edited via Streamlit
│   ├── saved_plans.json        # Persisted manual planning scenarios
│   └── networks/
│       └── default.json        # JSON snapshot of the canonical corridor (new loaders use this)
├── tests/
│   ├── test_basic.py           # Simulator + timeline smoke tests
│   ├── test_direction_logic.py # Corridor direction + spur rules
│   ├── test_models.py          # Dataclass behaviors
│   ├── test_mtbt_transform.py  # CSV → MTBT expansion helpers
│   ├── test_network_editor.py  # Spreadsheet parsing + spur helpers
│   ├── test_network_layout.py  # Graph layout heuristics
│   ├── test_network_loader.py  # JSON schema + layout overrides
│   └── test_schedule_service.py# MTBT dataframe validation
├── requirements.txt
├── pyproject.toml
├── ruff.toml                   # Linting + import-ordering configuration
├── mypy.ini                    # Strict typing rules
├── noxfile.py                  # lint/type/test automation entry points
├── ARCHITECTURE.md             # Comprehensive architecture documentation
└── README.md
```

## Setup
```powershell
python -m venv .venv
\.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Recommended for contributors: install extras defined in pyproject
pip install -e .[dev,ui]
```

If you prefer `pipx`/Conda, just make sure `python -m pip install -e .[dev,ui]` runs inside the environment you plan to use for Streamlit and the automated tests.

### First run checklist

1. **Prime the data** – copy or edit `data/networks/default.json` and `data/mtbt_schedule.csv` so they reflect the corridor you plan to simulate.
2. **Verify the toolchain** – run `nox -s lint typecheck tests` once to confirm Ruff, mypy, and pytest all succeed locally.
3. **Launch the dashboard** – start `streamlit run streamlit_app.py` and choose/duplicate a network via the sidebar before editing schedules or plans.

## Run the Streamlit dashboard
```powershell
streamlit run streamlit_app.py
```

Key pages inside the app:

1. **Automation vs Manual planning** – run the auto planner, tweak results manually, and persist custom plans.
2. **Timeline & diagnostics** – visualize movement/maintenance segments and machine state transitions.
3. **MTBT Schedule** – edit the CSV with grid filters, add/remove days, and apply the changes instantly to the simulator.

## MTBT data & persistence
- `data/mtbt_schedule.csv` is the single source of truth. The Streamlit MTBT editor loads it, validates columns, and rewrites the CSV when you click **Save schedule**. Commit this file whenever you want a historical record of the production plan.
- Uploads are validated to ensure every row has a `Segment Name`, at least one `YYYY-MM` column, and only non-negative numeric MTBT/Initial Load values, preventing bad data from entering the simulator.
- `data/networks/default.json` defines the corridor layout (stations, segments, direction metadata). The simulator now loads stations/segments from these JSON configs, so you can add more corridors by dropping additional files into `data/networks/`.
- The Streamlit network editor lets you duplicate, create, rename (display name), and now delete network JSON files directly from the UI with inline validation, so you can manage corridor snapshots without leaving the dashboard.
- `data/saved_plans.json` keeps manually curated scenarios. Saving/updating a plan inside the app overwrites the JSON; check it into version control if you need reproducible manual runs.
- When running in CI or headless contexts, provide your own MTBT CSV/JSON via the `data/` directory before launching the app.

## Developer workflow & tooling

| Task | Command | Notes |
| --- | --- | --- |
| Lint | `nox -s lint` | Runs Ruff using settings in `ruff.toml` (imports, style, safety rules). |
| Type-check | `nox -s typecheck` | Executes mypy with the strict config in `mypy.ini` and ensures the `src/` package stays typed. |
| Tests | `nox -s tests` | Installs `.[dev,ui]` extras, keeps `src/` + root on `PYTHONPATH` via `pyproject.toml`, and runs the full pytest suite (40 tests covering simulator, schedule, layout, editor, and planner helpers). |

You can still call `pytest -q`, `ruff check src tests`, or `python -m mypy src` directly, but the nox sessions guarantee the `PYTHONPATH` setup and dependency set match CI.

## Tests & quality

The test suite now spans end-to-end simulator smoke tests plus focused unit coverage for:

- Schedule services: CSV parsing, MTBT dataframe normalization, and summaries.
- Network loader/editor/layout helpers: JSON validation, coordinate normalization, and spur/allowed-movement parsing.
- Direction logic: corridor order, spur metadata, and move filtering.
- Streamlit UI plumbing: modular tab renderers in `src/railroad_frontend/views/` and shared session helpers in `src/railroad_frontend/state/session.py` keep auto/manual planners aligned and are covered by serialization tests.
- Backend architecture: domain logic in `src/railroad_backend/domain/` provides shared utilities for network editing, layout, persistence, and schedule management, while `src/railroad_backend/services/` handles high-level planning operations.
- Pytest discovery is configured in `pyproject.toml` so `pytest -q` or editor test runners work without hand-editing `PYTHONPATH`.

Run everything via:

```powershell
nox -s tests
```

or call `pytest -q` directly—thanks to the built-in path config it will locate `src/` modules without extra environment tweaks. Pair it with `nox -s lint typecheck` (or the individual `ruff`/`mypy` commands) before opening a PR.

> ℹ️ Looking to add CI? Point a GitHub Actions workflow at `nox -s lint typecheck tests` so pull requests keep the same gate as local contributors.

## Global direction model

- Corridor order (forward Carregado): TRO → TMI → ZTO → ZIQ → ZBV → ZKE → ZEV → ZPT → ZPG
- Spurs forward for Vazio: TMI → PSG and ZIQ → ZPD
  - Reverse directions are forward for Carregado
- Turning in place flips the global direction (Carregado ↔ Vazio)
- The facing displayed to the operator is always the label of the global direction

## Notes
- Turning at TRO, ZTO, ZPG, and ZPT consumes one day and flips the machine.
- Movement commands are validated so that maintenance can only occur when moving forward relative to the current global direction.

## License
MIT