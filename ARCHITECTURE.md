# Architecture Documentation

## Table of Contents
1. [Overview](#overview)
2. [Design Principles](#design-principles)
3. [System Architecture](#system-architecture)
4. [Module Organization](#module-organization)
5. [Data Flow](#data-flow)
6. [Domain Model](#domain-model)
7. [Core Components](#core-components)
8. [Testing Strategy](#testing-strategy)
9. [Configuration Management](#configuration-management)
10. [Extension Points](#extension-points)

---

## Overview

The Railroad Maintenance Simulator is a planning toolkit for optimizing MTBT (Mean Time Between Tamping) grinding maintenance across railroad corridors with spurs. The system uses a layered architecture with clear separation between domain logic, services, presentation, and infrastructure concerns.

### Key Design Goals

- **Maintainability**: Modular organization with clear boundaries and minimal coupling
- **Testability**: Pure business logic separated from I/O and UI concerns
- **Extensibility**: Support for multiple corridors, custom planning strategies, and new features
- **User Experience**: Interactive Streamlit dashboard with real-time visualization
- **Reliability**: Comprehensive validation and error handling at all layers

---

## Design Principles

### 1. Layered Architecture

The system follows a classic layered architecture pattern:

```
┌─────────────────────────────────────┐
│   Presentation Layer (Streamlit)    │  ← User Interface
├─────────────────────────────────────┤
│      Service Layer (Backend)        │  ← Business Operations
├─────────────────────────────────────┤
│    Domain Layer (Core Logic)        │  ← Business Rules
├─────────────────────────────────────┤
│   Infrastructure (Data, Persistence)│  ← External Systems
└─────────────────────────────────────┘
```

**Layer Responsibilities:**
- **Presentation**: Streamlit UI components, user interactions, visualization
- **Service**: High-level operations coordinating domain logic (auto/manual planning)
- **Domain**: Pure business logic (simulation engine, network graph, MTBT tracking)
- **Infrastructure**: File I/O, JSON/CSV parsing, data persistence

### 2. Domain-Driven Design

The core domain model represents real-world railroad concepts:
- **Entities**: Station, Segment, GrinderMachine
- **Value Objects**: NetworkConfig, NetworkMetadata, Movement
- **Services**: Simulator, AutoPlanner, ManualPlanner
- **Repositories**: PlanStorage (for persisting manual plans)

### 3. Separation of Concerns

Each module has a single, well-defined responsibility:
- `models/`: Domain entities (dataclasses)
- `simulator/`: Simulation engine and network navigation
- `railroad_backend/domain/`: Shared business logic utilities
- `railroad_backend/services/`: High-level planning orchestration
- `railroad_frontend/`: UI components and view logic
- `utils/`: Data transformation and loading utilities

### 4. Dependency Inversion

Higher layers depend on abstractions, not implementations:
- Services depend on domain interfaces
- UI components depend on service facades
- Domain logic has no dependencies on infrastructure

### 5. Pure Functions Where Possible

Most business logic is implemented as pure functions:
- `prepare_timeline_rows()`: Transforms simulation data to timeline format
- `validate_schedule_dataframe()`: Validates MTBT schedule data
- `build_network()`: Constructs network graph from configuration

---

## System Architecture

### High-Level Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     Streamlit Dashboard                       │
│  (streamlit_app.py + railroad_frontend/views/)               │
└────────────────────────┬─────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
┌────────────────┐ ┌──────────┐ ┌─────────────────┐
│ Auto Planner   │ │ Manual   │ │ Network Editor  │
│ Service        │ │ Planner  │ │ Service         │
└───────┬────────┘ └────┬─────┘ └────────┬────────┘
        │               │                 │
        └───────────────┼─────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │   Core Simulator Engine       │
        │   (simulator/core.py)         │
        └───────────┬───────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
┌────────────┐ ┌────────┐ ┌─────────────┐
│ Domain     │ │ Models │ │ Direction   │
│ Logic      │ │        │ │ Model       │
└────────────┘ └────────┘ └─────────────┘
        │           │           │
        └───────────┼───────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │   Data Layer                  │
        │   (JSON, CSV, Persistence)    │
        └───────────────────────────────┘
```

---

## Module Organization

### Directory Structure Rationale

```
src/
├── models/                      # Domain Entities
│   └── __init__.py             # Station, Segment, GrinderMachine
│
├── simulator/                   # Core Simulation Engine
│   ├── core.py                 # Main Simulator class
│   ├── direction_model.py      # Corridor direction logic
│   ├── network_utils.py        # Graph traversal helpers
│   └── timeline.py             # Timeline data preparation
│
├── railroad_backend/           # Backend Services & Domain Logic
│   ├── domain/                 # Shared business logic utilities
│   │   ├── network_editor.py  # Network editing/serialization
│   │   ├── network_layout.py  # Graph layout algorithms
│   │   ├── persistence.py     # Serialization utilities
│   │   ├── schedule.py        # MTBT schedule operations
│   │   ├── simulator.py       # Simulator exports
│   │   └── validation.py      # Validation utilities
│   │
│   ├── services/               # High-level business operations
│   │   ├── auto_planner.py    # Automated planning algorithm
│   │   ├── manual_planner.py  # Manual plan replay/validation
│   │   ├── network_editor.py  # Network editor facade
│   │   └── schedule_service.py# Schedule management facade
│   │
│   └── persistence/            # Data persistence
│       └── plan_storage.py    # Load/save manual plans
│
├── railroad_frontend/          # Presentation Layer
│   ├── components/             # Reusable UI components
│   │   └── timeline.py        # Timeline visualization
│   │
│   ├── state/                  # Session state management
│   │   └── session.py         # State keys and helpers
│   │
│   └── views/                  # Page-level views
│       ├── auto_simulation.py # Auto planner tab
│       ├── manual.py          # Manual planner tab
│       ├── comparison.py      # Comparison view
│       ├── network_editor.py  # Network editor tab
│       ├── mtbt_editor.py     # MTBT schedule editor
│       ├── schedule.py        # Schedule overview
│       └── overview.py        # Dashboard overview
│
└── utils/                      # Infrastructure Utilities
    ├── mtbt_transform.py      # MTBT data transformations
    ├── network_loader.py      # Network JSON loading
    └── timeline_generator.py  # Timeline visualization
```

### Module Design Rationale

**Why separate `railroad_backend` and `railroad_frontend`?**
- Clear boundary between business logic and presentation
- Backend can be tested without Streamlit dependencies
- Services can be reused in future CLI/API interfaces
- Frontend focuses purely on user interaction

**Why split `domain/` and `services/`?**
- `domain/`: Pure business logic, no orchestration
- `services/`: Coordinate multiple domain operations
- Services provide facades simplifying complex workflows

**Why keep `simulator/` separate from `railroad_backend`?**
- `simulator/` is the core engine, predating the backend refactor
- Maintains backward compatibility with existing tests
- Clear ownership: simulator is the "what", backend is the "how"

---

## Data Flow

### 1. Auto Planning Workflow

```
User Input (Streamlit)
    │
    ├─→ Start station, facing, date
    ├─→ Network selection
    └─→ MTBT schedule
    │
    ▼
AutoPlannerService.run_auto_plan_from_args()
    │
    ├─→ Parse schedule CSV → DataFrame
    ├─→ Build daily MTBT map
    ├─→ Initialize Simulator
    │
    ▼
Simulator Loop
    │
    ├─→ Check maintenance needs
    ├─→ Find valid moves (direction model)
    ├─→ Select move (priority logic)
    ├─→ Execute move/maintenance
    └─→ Record step in history
    │
    ▼
Timeline Generation
    │
    ├─→ prepare_timeline_rows()
    ├─→ TimelineGenerator.process_data()
    └─→ Generate visualization
    │
    ▼
Results Display (Streamlit)
    ├─→ Timeline plot
    ├─→ Metrics (days, maintenance count)
    └─→ Download options
```

### 2. Manual Planning Workflow

```
User Input (Streamlit)
    │
    ├─→ Load saved plan OR start new
    ├─→ View current state
    └─→ List available moves
    │
    ▼
ManualPlannerService.list_available_moves()
    │
    ├─→ Initialize Simulator to current state
    ├─→ Query valid moves (direction model)
    └─→ Return ManualMoveOption list
    │
    ▼
User Selects Move/Wait/Turn
    │
    └─→ Append to plan history
    │
    ▼
ManualPlannerService.replay_manual_plan()
    │
    ├─→ Initialize Simulator
    ├─→ Replay each step in sequence
    ├─→ Validate each action
    └─→ Return final state + timeline
    │
    ▼
Persistence (optional)
    │
    └─→ PlanStorage.save_manual_plan()
    │
    ▼
Results Display (Streamlit)
    ├─→ Timeline plot
    ├─→ Current machine state
    └─→ Comparison with auto plan
```

### 3. Schedule Management Workflow

```
User Uploads/Edits CSV (Streamlit)
    │
    ▼
ScheduleService.parse_schedule_bytes()
    │
    ├─→ pd.read_csv()
    ├─→ Validate columns (Segment Name, months)
    └─→ Return DataFrame
    │
    ▼
ScheduleService.validate_schedule_dataframe()
    │
    ├─→ Check for negative values
    ├─→ Ensure all segments present
    ├─→ Validate month format (YYYY-MM)
    └─→ Raise ValueError on errors
    │
    ▼
ScheduleService.build_daily_map()
    │
    ├─→ Expand months to daily MTBT values
    ├─→ Apply Initial Load if present
    └─→ Return DailyMap: {segment: {date: mtbt}}
    │
    ▼
Save to disk (data/mtbt_schedule.csv)
    │
    └─→ Single source of truth for all simulations
```

### 4. Network Editor Workflow

```
User Edits Network (Streamlit)
    │
    ├─→ Add/remove/edit stations
    ├─→ Add/remove/edit segments
    ├─→ Configure allowed movements
    └─→ Set corridor order & spurs
    │
    ▼
NetworkEditorService.serialize_network_editor_state()
    │
    ├─→ Validate station references
    ├─→ Parse spur text format
    ├─→ Validate segment structure
    └─→ Return JSON payload
    │
    ▼
Validation.validate_network_payload()
    │
    ├─→ Check required fields
    ├─→ Validate data types
    ├─→ Ensure referential integrity
    └─→ Raise errors if invalid
    │
    ▼
Save to disk (data/networks/{name}.json)
    │
    └─→ NetworkLoader.load_network() for reuse
```

---

## Domain Model

### Core Entities

#### Station
```python
@dataclass
class Station:
    name: str                    # Unique identifier (e.g., "TRO", "TMI")
    can_turn: bool = False       # Whether grinder can turn here
    segments: List[Segment]      # Adjacent segments
```

**Design Notes:**
- Stations are graph nodes in the network
- `can_turn` determines if turning maneuver is allowed
- `segments` list maintains bidirectional relationships

#### Segment
```python
@dataclass
class Segment:
    name: str                           # Unique identifier (e.g., "TRO-TMI")
    start_station: Station              # Origin
    end_station: Station                # Destination
    length: float                       # Kilometers
    load: float                         # Current MTBT accumulation
    maintenance_due: bool               # Threshold reached?
    mtbt_threshold: float               # Trigger for maintenance
    allowed_movements: List[Movement]   # Valid direction pairs
    move_time_days: int                 # Time to traverse
    maintenance_time_days: int          # Time to maintain
```

**Design Notes:**
- Segments track MTBT load over time
- `allowed_movements` enforce directional constraints
- Bidirectional registration with stations in `__post_init__`

#### GrinderMachine
```python
@dataclass
class GrinderMachine:
    front_car_position: Position        # Station or Segment
    rear_car_position: Position         # Station or Segment
    direction: str                      # "forward" or "backward"
    mode: str                           # "move" or "maintenance"
    facing: Optional[str]               # "Carregado" or "Vazio"
    global_direction: Optional[str]     # Corridor direction
    second_kld_installed: bool          # Equipment flag
```

**Design Notes:**
- Maintains both physical position and logical direction
- `global_direction` tracks position in corridor (for spur logic)
- `facing` is derived from `global_direction` for operator display

### Value Objects

#### NetworkConfig
```python
@dataclass
class NetworkConfig:
    name: str
    stations: Dict[str, Station]
    segments: List[Segment]
    metadata: NetworkMetadata
    layout: NetworkLayout
```

#### NetworkMetadata
```python
@dataclass
class NetworkMetadata:
    corridor_order: Sequence[str]                   # Station sequence
    spur_forward_carregado: Sequence[Tuple[str, str]]
    spur_forward_vazio: Sequence[Tuple[str, str]]
```

**Design Notes:**
- Metadata defines corridor topology
- Spurs are direction-dependent (Carregado vs Vazio)
- Used by direction model to filter valid moves

---

## Core Components

### 1. Simulator (simulator/core.py)

**Purpose**: Execute simulation steps with state management

**Key Methods:**
```python
def init_machine(start_station, facing_station, start_date, daily_map):
    """Initialize grinder position and simulation date"""

def turn_to(station_name: str) -> bool:
    """Execute turning maneuver (flips global direction)"""

def wait_days(days: int) -> bool:
    """Advance simulation date, accumulate MTBT"""

def move_to(segment, next_station, action: str) -> Dict:
    """Execute move ('v' = empty, 'm' = maintenance)"""

def classify_edge_direction(start, end) -> str:
    """Determine if move is 'CARREGADO', 'VAZIO', or 'SPUR'"""
```

**State Management:**
- `self.steps`: Full history of all actions
- `self.simulation_date`: Current date in simulation
- `self.daily_map`: MTBT accumulation schedule
- `self.machine`: Current grinder state

**Design Decisions:**
- **Why mutable state?** Simulation is inherently stateful
- **Why return step dicts?** Enables replay and debugging
- **Why separate move/maintenance?** Different semantics and validations

### 2. Direction Model (simulator/direction_model.py)

**Purpose**: Enforce corridor topology and spur rules

**Key Functions:**
```python
def _direction_model_from_metadata(metadata: NetworkMetadata) -> DirectionModel:
    """Build direction classifier from network metadata"""

def _classify_edge_global_dir(model, start, end) -> Optional[str]:
    """Classify move as CARREGADO, VAZIO, or SPUR"""

def _filter_moves_by_direction(model, moves, global_dir) -> List:
    """Remove moves not aligned with current global direction"""
```

**Rules:**
- Corridor order defines CARREGADO direction (forward)
- Reverse is VAZIO direction
- Spurs have direction-specific rules:
  - `spur_forward_carregado`: Only traversable when global_dir = CARREGADO
  - `spur_forward_vazio`: Only traversable when global_dir = VAZIO

**Design Decisions:**
- **Why global direction?** Matches operational reality (grinder has orientation)
- **Why spur metadata?** Branch lines have asymmetric access patterns
- **Why filter at query time?** Simplifies validation logic

### 3. Auto Planner (railroad_backend/services/auto_planner.py)

**Purpose**: Automated maintenance planning with priority heuristics

**Algorithm:**
```python
def run_auto_plan_from_args(config: AutoPlanConfig):
    """
    1. Initialize simulator with start position and schedule
    2. Loop until max_days or all maintenance complete:
        a. Find segments requiring maintenance
        b. Find reachable segments from current position
        c. Prioritize: maintenance_aligned > closest > alphabetical
        d. Execute move or wait if no valid move
    3. Return results with timeline and metrics
    """
```

**Priority Logic:**
1. **Maintenance-aligned**: Move results in maintenance action
2. **Distance**: Prefer closer segments (fewer move days)
3. **Alphabetical**: Deterministic tiebreaker

**Design Decisions:**
- **Why greedy algorithm?** Simple, fast, produces reasonable plans
- **Why not optimal?** NP-hard problem, good-enough solutions acceptable
- **Why expose result structure?** Enable comparison with manual plans

### 4. Manual Planner (railroad_backend/services/manual_planner.py)

**Purpose**: User-guided planning with validation

**Key Functions:**
```python
def list_available_moves(config, plan) -> List[ManualMoveOption]:
    """Query valid moves from current state"""

def replay_manual_plan(config, plan) -> ManualPlanResult:
    """Execute plan step-by-step with validation"""

def validate_manual_plan_step(step: Dict) -> None:
    """Ensure step has required fields and valid values"""
```

**Plan Structure:**
```python
{
    "type": "wait" | "turn" | "move",
    "days": int,              # for wait
    "station": str,           # for turn
    "segment": str,           # for move
    "destination": str,       # for move
    "action": "v" | "m"       # for move (empty/maintenance)
}
```

**Design Decisions:**
- **Why separate list_available_moves?** Enable UI to show valid options
- **Why replay?** Ensure plan validity, generate timeline
- **Why validate steps?** Catch user errors early with clear messages

### 5. Schedule Service (railroad_backend/services/schedule_service.py)

**Purpose**: MTBT schedule management and validation

**Key Functions:**
```python
def parse_schedule_bytes(data: bytes) -> pd.DataFrame:
    """Parse uploaded CSV to DataFrame"""

def validate_schedule_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate required columns, data types, ranges"""

def build_daily_map(df: pd.DataFrame, year: int) -> DailyMap:
    """Expand monthly MTBT values to daily accumulation map"""

def schedule_missing_segments(df, network) -> List[str]:
    """Find schedule entries not present in network"""
```

**Validation Rules:**
- Must have `Segment Name` column
- At least one `YYYY-MM` formatted column
- All MTBT/Initial Load values non-negative
- Optional: `Initial Load` column for starting values

**Design Decisions:**
- **Why DataFrame?** Pandas provides rich data manipulation
- **Why monthly granularity?** Matches operational planning cycles
- **Why build_daily_map?** Simulator operates on daily time steps

### 6. Network Editor (railroad_backend/services/network_editor.py)

**Purpose**: Network configuration editing and serialization

**Key Functions:**
```python
def serialize_network_editor_state(state: Dict) -> Dict:
    """Convert UI state to network JSON payload"""

def station_choices_from_config(config) -> List[str]:
    """Get list of station names for dropdowns"""

def facing_options_from_config(config, station) -> List[str]:
    """Get valid facing options from a station"""

def default_segment_name_sequence(network) -> str:
    """Generate default segment order for schedule"""
```

**State Management:**
- `corridor_text`: Newline-separated station order
- `spur_carregado_text`: Spur pairs for Carregado direction
- `spur_vazio_text`: Spur pairs for Vazio direction
- `segments_df`: DataFrame of segment properties
- `stations_list`: List of station configurations

**Design Decisions:**
- **Why text format for spurs?** User-friendly input method
- **Why serialize to JSON?** Standard interchange format
- **Why separate facing options?** Context-dependent valid choices

---

## Testing Strategy

### Test Organization

```
tests/
├── test_basic.py              # Smoke tests for simulator and timeline
├── test_models.py             # Dataclass behavior and invariants
├── test_direction_logic.py    # Corridor and spur direction rules
├── test_network_loader.py     # JSON parsing and validation
├── test_network_editor.py     # State serialization and parsing
├── test_network_layout.py     # Graph layout algorithms
├── test_mtbt_transform.py     # MTBT data transformations
├── test_schedule_service.py   # Schedule validation and processing
├── test_validation.py         # Input validation utilities
├── test_edge_cases.py         # Boundary conditions and error paths
└── test_integration.py        # End-to-end workflow tests
```

### Test Coverage Layers

**1. Unit Tests** (test_models.py, test_mtbt_transform.py)
- Test individual functions in isolation
- Mock external dependencies
- Focus on business logic correctness

**2. Component Tests** (test_simulator, test_direction_logic.py)
- Test module-level interactions
- Use real data structures, mock I/O
- Validate component contracts

**3. Integration Tests** (test_integration.py)
- Test complete workflows end-to-end
- Use temporary files for I/O
- Validate cross-service coordination

**4. Edge Case Tests** (test_edge_cases.py)
- Boundary conditions (empty networks, missing data)
- Error paths (invalid input, constraint violations)
- Performance edge cases (large networks, long simulations)

### Test Fixtures and Patterns

**Common Patterns:**
```python
# Temporary file fixtures
def test_with_temp_network(tmp_path):
    network_file = tmp_path / "network.json"
    network_file.write_text(json.dumps(payload))
    config = load_network(network_file)
    # test with config

# Parametrized tests for multiple scenarios
@pytest.mark.parametrize("input,expected", [
    ("valid_input", "expected_output"),
    ("edge_case", "expected_edge_output"),
])
def test_transformation(input, expected):
    assert transform(input) == expected

# Error validation
def test_invalid_input_raises():
    with pytest.raises(ValueError, match="expected error message"):
        dangerous_function(invalid_input)
```

### Test Design Principles

1. **Independence**: Each test runs in isolation
2. **Repeatability**: Same inputs always produce same outputs
3. **Clarity**: Test names describe what is tested
4. **Fast**: Unit tests run in milliseconds
5. **Comprehensive**: Cover normal paths, edge cases, error paths

---

## Configuration Management

### Configuration Files

**1. Network Configuration** (`data/networks/*.json`)
```json
{
  "name": "Corridor Name",
  "stations": [
    {"name": "TRO", "can_turn": true},
    {"name": "TMI", "can_turn": true}
  ],
  "segments": [
    {
      "name": "TRO-TMI",
      "start": "TRO",
      "end": "TMI",
      "length_km": 50.0,
      "mtbt_threshold": 1000.0,
      "move_time_days": 2,
      "maintenance_time_days": 5,
      "allowed_movements": [["TRO", "TMI"], ["TMI", "TRO"]]
    }
  ],
  "direction_model": {
    "corridor_order": ["TRO", "TMI", ...],
    "spur_forward_carregado": [["TMI", "PSG"]],
    "spur_forward_vazio": [["ZIQ", "ZPD"]]
  },
  "layout": {
    "mode": "table",
    "table_overrides": {"TRO": {"x": 0, "y": 0}},
    "scale": 1.0
  }
}
```

**2. MTBT Schedule** (`data/mtbt_schedule.csv`)
```csv
Segment Name,Initial Load,2024-01,2024-02,2024-03,...
TRO-TMI,500,1000,1000,1000,...
TMI-ZTO,0,800,800,800,...
```

**3. Saved Plans** (`data/saved_plans.json`)
```json
{
  "plan_name": {
    "network_path": "data/networks/default.json",
    "start_station": "TRO",
    "facing_station": "TMI",
    "start_date": "2024-01-01",
    "plan": [
      {"type": "wait", "days": 5},
      {"type": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "m"}
    ]
  }
}
```

### Configuration Validation

**Network Validation** (railroad_backend/domain/validation.py):
- Required fields present (name, stations, segments)
- Station references exist in station list
- Segment references valid stations
- Allowed movements reference valid station pairs
- Corridor order contains only defined stations
- Spur pairs reference valid station pairs

**Schedule Validation** (railroad_backend/services/schedule_service.py):
- `Segment Name` column present
- At least one month column (`YYYY-MM` format)
- All numeric values non-negative
- Optional `Initial Load` column validated
- Warns if segments in schedule not in network

**Plan Validation** (railroad_backend/services/manual_planner.py):
- Each step has required fields (`type`, action-specific fields)
- Move actions have valid `action` field ('v' or 'm')
- Station/segment references exist in network
- Turn stations allow turning (`can_turn = true`)

---

## Extension Points

### Adding New Planning Algorithms

**Current**: Auto planner uses greedy heuristics
**Extension**: Implement alternative strategies

```python
# New file: railroad_backend/services/genetic_planner.py
def run_genetic_plan(config: AutoPlanConfig) -> AutoPlanResult:
    """Genetic algorithm for optimal maintenance scheduling"""
    # 1. Generate initial population of plans
    # 2. Evaluate fitness (days, maintenance coverage)
    # 3. Select, crossover, mutate
    # 4. Return best plan
```

**Integration**: Register in Streamlit dropdown
```python
PLANNER_OPTIONS = {
    "Greedy": run_auto_plan_from_args,
    "Genetic": run_genetic_plan,
}
selected = st.selectbox("Algorithm", PLANNER_OPTIONS.keys())
planner_func = PLANNER_OPTIONS[selected]
```

### Adding New Visualization Types

**Current**: Timeline plot via matplotlib
**Extension**: Add interactive Gantt chart

```python
# railroad_frontend/components/gantt.py
def render_gantt_chart(timeline_data: List[Dict]) -> None:
    """Plotly-based interactive Gantt chart"""
    import plotly.express as px
    fig = px.timeline(timeline_data, x_start="start", x_end="end", y="segment")
    st.plotly_chart(fig)
```

**Integration**: Add option in view
```python
viz_type = st.radio("Visualization", ["Timeline", "Gantt"])
if viz_type == "Timeline":
    render_timeline(plot)
else:
    render_gantt_chart(timeline_rows)
```

### Adding New Validation Rules

**Current**: Basic validation in domain/validation.py
**Extension**: Add custom business rules

```python
# railroad_backend/domain/custom_rules.py
class ValidationRule:
    def validate(self, config: NetworkConfig) -> List[str]:
        """Return list of error messages"""
        raise NotImplementedError

class MinSegmentLengthRule(ValidationRule):
    def validate(self, config: NetworkConfig) -> List[str]:
        errors = []
        for seg in config.segments:
            if seg.length < 10.0:
                errors.append(f"Segment {seg.name} too short: {seg.length}km")
        return errors

# Register in validation pipeline
RULES = [MinSegmentLengthRule(), ...]
```

### Adding REST API Layer

**Current**: Streamlit-only interface
**Extension**: Add FastAPI backend

```python
# api/main.py
from fastapi import FastAPI
from railroad_backend.services.auto_planner import run_auto_plan_from_args

app = FastAPI()

@app.post("/api/plan/auto")
def create_auto_plan(config: AutoPlanConfig):
    result = run_auto_plan_from_args(config)
    return result.to_dict()

@app.get("/api/networks/{name}")
def get_network(name: str):
    config = load_network(f"data/networks/{name}.json")
    return config.to_dict()
```

**Benefits**:
- Enable programmatic access
- Support mobile/web clients
- Integrate with external systems

### Adding Database Persistence

**Current**: JSON file persistence
**Extension**: Add SQLAlchemy models

```python
# railroad_backend/persistence/database.py
from sqlalchemy import Column, Integer, String, Float, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class NetworkModel(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    config = Column(JSON)

class PlanModel(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    network_id = Column(Integer, ForeignKey("networks.id"))
    plan_data = Column(JSON)
```

**Benefits**:
- Concurrent access
- Query capabilities
- Audit trails

---

## Design Decisions and Rationale

### Why Streamlit?

**Pros**:
- Rapid prototyping and iteration
- Python-native (no frontend frameworks)
- Built-in widgets and charts
- Suitable for internal tools

**Cons**:
- Limited customization
- Session state management quirks
- Not suitable for public-facing apps

**Decision**: Streamlit is ideal for this internal planning tool used by domain experts.

### Why Not Object-Oriented Design?

The codebase uses dataclasses and functions rather than inheritance hierarchies:

**Pros**:
- Simpler to understand and test
- Less coupling between components
- Easier to serialize/deserialize
- More Pythonic (favors composition)

**Cons**:
- Less encapsulation of behavior
- Some code duplication

**Decision**: Functional style with dataclasses fits the domain (data-centric operations).

### Why Mutable Simulator State?

The Simulator class maintains mutable state rather than immutable:

**Pros**:
- Matches mental model of simulation
- Efficient (no copying for each step)
- Easier to debug (inspect current state)

**Cons**:
- Harder to reason about in concurrent contexts
- Testing requires setup/teardown

**Decision**: Simulation is inherently stateful; mutable design is natural fit.

### Why Not Event Sourcing?

Alternative: Store all events, rebuild state by replaying

**Pros of Event Sourcing**:
- Complete audit trail
- Time-travel debugging
- Easy to add new projections

**Cons**:
- More complex
- Overkill for single-user tool
- Performance overhead

**Decision**: Simple state tracking sufficient for current needs. Can migrate later if needed.

---

## Future Architectural Improvements

### 1. Command Query Responsibility Segregation (CQRS)

Separate read models from write models:
```python
# Commands (writes)
def execute_move(command: MoveCommand) -> None:
    """Mutate simulator state"""

# Queries (reads)
def get_available_moves(query: AvailableMovesQuery) -> List[Move]:
    """Read-only view of valid moves"""
```

### 2. Plugin Architecture

Support external extensions:
```python
class PlannerPlugin:
    def plan(self, config: Config) -> Result:
        raise NotImplementedError

# User-defined plugins
class CustomPlanner(PlannerPlugin):
    def plan(self, config):
        # Custom algorithm
```

### 3. Async Operations

For long-running simulations:
```python
import asyncio

async def run_simulation_async(config):
    """Non-blocking simulation execution"""
    # Enable progress updates during execution
```

### 4. Microservices

Split into independent services:
- Simulation Service (core engine)
- Planning Service (algorithms)
- Visualization Service (timeline generation)
- API Gateway (routing)

### 5. Domain Events

Publish events for state changes:
```python
class MoveCompleted(Event):
    segment: str
    timestamp: datetime

# Subscribers
def on_move_completed(event: MoveCompleted):
    log_analytics(event)
    update_dashboard(event)
```

---

## Conclusion

The Railroad Maintenance Simulator demonstrates a well-structured, layered architecture with clear separation of concerns. The design prioritizes:

- **Maintainability**: Modular organization with focused responsibilities
- **Testability**: 100+ tests covering unit, component, integration, and edge cases
- **Extensibility**: Multiple extension points for new features
- **Usability**: Interactive Streamlit dashboard for domain experts

The architecture strikes a balance between simplicity (avoiding over-engineering) and robustness (comprehensive validation and error handling), making it suitable for the operational planning needs of railroad maintenance teams.

---

**Last Updated**: December 2024  
**Version**: 0.5.0
