"""Automated planning service built on top of the simulator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE
from src.railroad_backend.domain.schedule import build_daily_map
from src.utils.mtbt_transform import get_initial_loads

from ..domain.simulator import DEFAULT_NETWORK_FILE, Simulator
from .network_editor import (
    default_facing_station_from_config,
    default_start_station_from_config,
)

if TYPE_CHECKING:
    from src.utils.network_loader import NetworkConfig


@dataclass
class AutoPlanConfig:
    csv_path: Path
    start_station: str
    facing_station: str
    start_year: int
    end_year: int
    second_kld: bool
    steps: int = 0
    network_source: Optional[Union[str, Path]] = None
    strategy: str = "greedy"
    ilp_window_days: int = 60
    ilp_weight_coverage: float = 10.0
    ilp_weight_travel: float = 1.0
    ilp_weight_proximity: float = 0.5
    ilp_time_limit_s: float = 20.0

    def __post_init__(self) -> None:
        """Validate configuration after initialization.
        
        Raises:
            ValueError: If configuration parameters are invalid.
        """
        # Validate CSV path
        if not isinstance(self.csv_path, Path):
            raise TypeError(f"csv_path must be Path, got {type(self.csv_path).__name__}")
        if not self.csv_path.exists():
            raise ValueError(f"Schedule file not found: {self.csv_path}")
        if not self.csv_path.is_file():
            raise ValueError(f"Schedule path is not a file: {self.csv_path}")
        
        # Validate station names
        start = self.start_station.strip() if isinstance(self.start_station, str) else ""
        facing = self.facing_station.strip() if isinstance(self.facing_station, str) else ""
        if not start:
            raise ValueError("start_station cannot be empty or whitespace")
        if not facing:
            raise ValueError("facing_station cannot be empty or whitespace")
        
        # Validate years
        if not isinstance(self.start_year, int):
            raise TypeError(f"start_year must be int, got {type(self.start_year).__name__}")
        if not isinstance(self.end_year, int):
            raise TypeError(f"end_year must be int, got {type(self.end_year).__name__}")
        if not (1900 <= self.start_year <= 2200):
            raise ValueError(f"start_year must be between 1900 and 2200, got {self.start_year}")
        if not (1900 <= self.end_year <= 2200):
            raise ValueError(f"end_year must be between 1900 and 2200, got {self.end_year}")
        if self.end_year < self.start_year:
            raise ValueError(f"end_year ({self.end_year}) cannot be before start_year ({self.start_year})")
        
        # Validate steps
        if not isinstance(self.steps, int):
            raise TypeError(f"steps must be int, got {type(self.steps).__name__}")
        if self.steps < 0:
            raise ValueError(f"steps must be non-negative, got {self.steps}")
        
        # Validate network source if provided
        if self.network_source is not None:
            if isinstance(self.network_source, str):
                net_path = Path(self.network_source)
            elif isinstance(self.network_source, Path):
                net_path = self.network_source
            else:
                raise TypeError(f"network_source must be str or Path, got {type(self.network_source).__name__}")
            if not net_path.exists():
                raise ValueError(f"Network file not found: {net_path}")


def _apply_initial_loads(sim: Simulator, csv_path: Path) -> None:
    """Apply initial segment loads from CSV to simulator.

    Args:
        sim: Simulator instance to update.
        csv_path: Path to MTBT schedule CSV containing 'Initial Load' column.
    """
    loads = get_initial_loads(str(csv_path))
    for seg in sim.segments:
        if seg.name in loads:
            seg.load_curva = loads[seg.name]
            seg.load_tangente = loads[seg.name]
            if seg.mtbt_threshold_curva:
                seg.maintenance_due_curva = seg.load_curva >= seg.mtbt_threshold_curva
            if seg.mtbt_threshold_tangente:
                seg.maintenance_due_tangente = seg.load_tangente >= seg.mtbt_threshold_tangente
            seg.maintenance_due = seg.maintenance_due_curva or seg.maintenance_due_tangente


def _init_simulation(config: AutoPlanConfig) -> Simulator:
    """Create and initialize a simulator from auto plan configuration.

    Args:
        config: Configuration specifying network, start/end dates, and MTBT schedule.

    Returns:
        Initialized Simulator instance ready for automatic planning.
    """
    network_ref = config.network_source or str(DEFAULT_NETWORK_FILE)
    sim = Simulator(network_ref)
    daily_map = build_daily_map(config.csv_path, config.start_year, config.end_year)
    sim.init_machine(
        start_station_name=config.start_station,
        facing_station_name=config.facing_station,
        start_year=config.start_year,
        second_kld_installed=config.second_kld,
        daily_map=daily_map,
    )
    _apply_initial_loads(sim, config.csv_path)
    return sim


from .auto_planner_strategies.base import AutoPlanStrategy, StepDecision
from .auto_planner_strategies.greedy import GreedyUrgencyStrategy
from .auto_planner_strategies.greedy import component_due as _component_due
from .auto_planner_strategies.greedy import days_until_next_threshold as _days_until_next_threshold
from .auto_planner_strategies.greedy import maintenance_action_for as _maintenance_action_for
from .auto_planner_strategies.greedy import needs_maintenance as _needs_maintenance
from .auto_planner_strategies.greedy import segments_already_due as _segments_already_due
from .auto_planner_strategies.rolling_horizon_ilp import RollingHorizonILPStrategy

# NOTE: _component_due/_needs_maintenance/_maintenance_action_for/
# _segments_already_due/_days_until_next_threshold are re-exported here
# (rather than only living in auto_planner_strategies/greedy.py) because
# tests/test_edge_cases.py imports them directly from this module. The
# strategy logic itself now lives in GreedyUrgencyStrategy.

STRATEGY_REGISTRY: Dict[str, "type[AutoPlanStrategy]"] = {
    "greedy": GreedyUrgencyStrategy,
    "rolling_ilp": RollingHorizonILPStrategy,
}


def _resolve_strategy(config: "AutoPlanConfig") -> AutoPlanStrategy:
    strategy_cls = STRATEGY_REGISTRY.get(config.strategy)
    if strategy_cls is None:
        raise ValueError(f"Unknown Auto Planner strategy: {config.strategy!r}. Known: {sorted(STRATEGY_REGISTRY)}")
    if config.strategy == "rolling_ilp":
        return RollingHorizonILPStrategy(
            window_days=config.ilp_window_days,
            weight_coverage=config.ilp_weight_coverage,
            weight_travel=config.ilp_weight_travel,
            weight_proximity=config.ilp_weight_proximity,
            time_limit_s=config.ilp_time_limit_s,
        )
    return strategy_cls()


def _execute_decision(sim: Simulator, decision: StepDecision) -> bool:
    """Execute a StepDecision against the real simulator. Returns True if progress was made."""
    if decision.kind == "move":
        sim.move_to(decision.segments, decision.next_station, action=decision.action)
        return True
    if decision.kind == "wait":
        return bool(sim.wait_days(decision.wait_days))
    if decision.kind == "turn":
        return sim.flip_global_direction()
    return False


@dataclass
class AutoPlanResult:
    """Result of automatic planning execution.

    Attributes:
        simulator: The simulator instance after plan execution.
        stop_reason: Reason planning stopped ('year_limit', 'steps_limit', or 'no_moves').
        stop_details: Additional details about the stopping condition.
    """
    simulator: Simulator
    stop_reason: str
    stop_details: Dict[str, str]
    strategy_name: str = "greedy"


def run_auto_plan(config: AutoPlanConfig) -> AutoPlanResult:
    sim = _init_simulation(config)
    strategy = _resolve_strategy(config)
    limit_date = datetime(config.end_year, 12, 31)
    stop_reason = "steps_limit"
    for _ in range(config.steps):
        decision = strategy.decide_next_action(sim)
        progressed = _execute_decision(sim, decision)
        if not progressed:
            stop_reason = "stalled"
            break
        if sim.simulation_date and sim.simulation_date.date() > limit_date.date():
            stop_reason = "year_limit"
            break
    else:
        stop_reason = "steps_limit"
    stop_details_obj: Dict[str, object] = {
        "limit_date": limit_date.date().isoformat(),
        "steps_requested": str(config.steps),
        "steps_completed": str(len(sim.steps)),
    }
    sim.stop_reason = stop_reason
    sim.stop_details = stop_details_obj
    stop_details_for_result: Dict[str, str] = {
        "limit_date": limit_date.date().isoformat(),
        "steps_requested": str(config.steps),
        "steps_completed": str(len(sim.steps)),
    }
    return AutoPlanResult(
        simulator=sim,
        stop_reason=stop_reason,
        stop_details=stop_details_for_result,
        strategy_name=config.strategy,
    )


def run_auto_plan_from_args(
    csv_path: Union[str, Path],
    *,
    start_station: str,
    facing_station: str,
    start_year: int,
    end_year: int,
    steps: int,
    second_kld: bool,
    network_source: Optional[Union[str, Path]] = None,
    strategy: str = "greedy",
    ilp_window_days: int = 60,
    ilp_weight_coverage: float = 10.0,
    ilp_weight_travel: float = 1.0,
    ilp_weight_proximity: float = 0.5,
    ilp_time_limit_s: float = 20.0,
) -> AutoPlanResult:
    config = AutoPlanConfig(
        csv_path=Path(csv_path),
        start_station=start_station,
        facing_station=facing_station,
        start_year=start_year,
        end_year=end_year,
        steps=steps,
        second_kld=second_kld,
        network_source=network_source,
        strategy=strategy,
        ilp_window_days=ilp_window_days,
        ilp_weight_coverage=ilp_weight_coverage,
        ilp_weight_travel=ilp_weight_travel,
        ilp_weight_proximity=ilp_weight_proximity,
        ilp_time_limit_s=ilp_time_limit_s,
    )
    return run_auto_plan(config)


def auto_defaults(config: "NetworkConfig") -> Dict[str, Any]:
    start_station = default_start_station_from_config(config)
    facing_station = default_facing_station_from_config(config, start_station)
    return {
        "start_station": start_station,
        "facing_station": facing_station,
        "start_year": 2025,
        "end_year": 2026,
        "steps": 20,
        "second_kld": False,
    }


def initialize_simulation_from_args(
    csv_path: Union[str, Path],
    *,
    start_station: str,
    facing_station: str,
    start_year: int,
    end_year: int,
    second_kld: bool,
    network_source: Optional[Union[str, Path]] = None,
) -> Simulator:
    config = AutoPlanConfig(
        csv_path=Path(csv_path),
        start_station=start_station,
        facing_station=facing_station,
        start_year=start_year,
        end_year=end_year,
        steps=0,
        second_kld=second_kld,
        network_source=network_source,
    )
    return _init_simulation(config)


__all__ = [
    "AutoPlanConfig",
    "AutoPlanResult",
    "run_auto_plan",
    "run_auto_plan_from_args",
    "initialize_simulation_from_args",
    "auto_defaults",
]
