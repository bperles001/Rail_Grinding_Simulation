# Changelog

All notable changes to this project will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) |
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Fixed
- Trechos com Singela + Linha Principal/Desviada (LP/LD) agora são tratados
  como um único passo lógico de deslocamento/manutenção que afeta os dois
  segmentos físicos juntos (MTBT, vencimento e duração somados), em vez de
  serem oferecidos como rotas alternativas independentes. Trechos sem
  Singela (só Carregado/Vazio) não mudam. `get_possible_moves()`/
  `Simulator.move_to()` agora trabalham com tuplas de 1-2 segmentos;
  `Simulator.move_to()` continua aceitando um único `Segment` normalmente.
- Classificação Carregado/Vazio de trechos LP/LD (e C/V) passou a usar a
  identidade do segmento (sufixo do nome) em vez de "qual estação de
  partida" — um segmento unidirecional só pode ser percorrido no seu único
  sentido permitido, então a conta antiga sempre dava Carregado e nunca
  Vazio, travando a manutenção em "só Move" depois de qualquer Turn.
- `init_machine()` (configuração de início/frente) usava uma classificação
  Carregado/Vazio diferente da usada depois em cada movimento — podia
  iniciar a máquina "de frente" para um trecho que nunca batia com o
  próprio sentido dela, travando manutenção em "só Move" desde o primeiro
  passo. Os dois pontos agora usam a mesma lógica.

### Added
- Manual Route: ao adicionar um passo de Manutenção/Só curvas num trecho
  com Singela + LP/LD, dá pra escolher manter só a Singela, só o pátio
  (LP/LD), ou os dois — útil quando um dos dois já foi esmerilhado numa
  passada anterior e não precisa repetir. Auto Simulation não muda.
- Manual Route plan steps can now override the day-count of a single
  move/maintenance step (`days_override`) without changing the segment's
  base `move_time_days`/`maintenance_time_days` — the Days cell in the plan
  table is editable for Traverse rows too, not just Wait rows. Auto
  Simulation is unaffected.
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
  `parse_station_coordinates` also tolerates Brazilian-locale decimal-comma
  input pasted straight from Excel (e.g. `RDA,-15,55,-54,56`), and
  semicolon-separated fields.
- `schematic_layout_from_seed` gained an `octilinear` option (default on):
  snaps each edge's angle to the nearest 45° before placing the next
  station, the standard technique behind metro-map-style schematics - same
  topology/shape, but clean horizontal/vertical/diagonal lines instead of
  arbitrary angles.
- Network sketch: segments between the same station pair are now drawn to
  reflect real track layout instead of overlapping straight lines. Where a
  shared Singela plus Carregado (LP)/Vazio (LD) all exist between a pair,
  Singela is drawn as a continuous line with Carregado inline through the
  middle (the "Linha Principal" stays straight) and Vazio as a siding loop
  that splits off and rejoins (the "Linha Desviada" bows out) - matching
  real trackwork where the main line runs straight and the passing siding
  is what curves away. Where only Carregado+Vazio exist (no shared track,
  e.g. SP Sul), they're drawn as straight parallel lines. Stations that can
  turn (`can_turn`) are colored distinctly from regular stations, with a
  legend. Node circles are large enough for the 3-letter station code to
  render inside them, always on top of the segment lines.

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
