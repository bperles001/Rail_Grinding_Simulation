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


def _component_due(seg, component: str) -> bool:
    """Check if a single component (curva or tangente) has reached its threshold.

    Mirrors the pre-split semantics: an explicit 0 threshold still counts as
    "configured" (>= comparison applies); only a `None` threshold means "not
    configured" and never triggers maintenance.
    """
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    load = getattr(seg, f"load_{component}", 0.0) or 0.0
    if threshold is None:
        return False
    try:
        return float(load) >= float(threshold)
    except (TypeError, ValueError):  # pragma: no cover
        return False


def _needs_maintenance(seg) -> bool:
    """Check if the segment's curva or tangente load exceeds its threshold.

    Args:
        seg: Segment object with load_curva/load_tangente and
            mtbt_threshold_curva/mtbt_threshold_tangente attributes.

    Returns:
        True if either component needs maintenance.
    """
    return _component_due(seg, "curva") or _component_due(seg, "tangente")


def _maintenance_action_for(seg) -> str:
    """Pick maintain_curves when only curva is due, full maintain otherwise.

    There is no "tangente only" action: a full grind covers both components,
    so it's the correct choice whenever tangente is due (curva or not).
    """
    if _component_due(seg, "tangente"):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES


def _segments_already_due(sim: Simulator) -> bool:
    """Check if any segments require immediate maintenance.

    Args:
        sim: Simulator instance.

    Returns:
        True if any segment needs maintenance.
    """
    return any(_needs_maintenance(seg) for seg in sim.segments)


def _days_until_next_threshold(sim: Simulator, *, scan_limit_days: int = 180) -> int:
    """Calculate days until next segment reaches MTBT threshold.

    Args:
        sim: Simulator with daily_map and simulation_date.
        scan_limit_days: Maximum days to scan ahead.

    Returns:
        Days until next threshold, or 0 if already due or no daily map.
    """
    if not sim.daily_map or not sim.simulation_date:
        return 0
    projected: Dict[str, float] = {}
    thresholds: Dict[str, float] = {}
    component_seg_name: Dict[str, str] = {}
    for seg in sim.segments:
        for component, threshold, load in (
            (f"{seg.name}::curva", seg.mtbt_threshold_curva, seg.load_curva),
            (f"{seg.name}::tangente", seg.mtbt_threshold_tangente, seg.load_tangente),
        ):
            if threshold in (None, 0):
                continue
            thresholds[component] = float(threshold)
            projected[component] = float(load or 0.0)
            component_seg_name[component] = seg.name
    if not thresholds:
        return 0
    if _segments_already_due(sim):
        return 0
    # Cache daily values for all components to reduce dict lookups
    cached_daily_vals = {
        component: sim.daily_map.get(component_seg_name[component]) or {}
        for component in thresholds
    }
    current = sim.simulation_date
    for offset in range(1, scan_limit_days + 1):
        date_str = (current + timedelta(days=offset - 1)).strftime("%Y-%m-%d")
        progressed = False
        for component, threshold in thresholds.items():
            daily_values = cached_daily_vals[component]
            increment = daily_values.get(date_str)
            if increment:
                projected[component] = projected.get(component, 0.0) + float(increment)
                progressed = True
            if projected.get(component, 0.0) >= threshold:
                return offset
        if not progressed:
            # Early exit: if no component had data today, check if any future data exists
            if not any(daily_vals.get(date_str) for daily_vals in cached_daily_vals.values()):
                break
    return 0


def _move_priority(pair) -> Tuple[int, float, str]:
    """Calculate move priority for sorting (urgent first, then by load).

    Args:
        pair: Tuple of (segment, destination_station).

    Returns:
        Tuple of (urgency, negative_load, segment_name) for sorting.
    """
    seg, _ = pair
    urgent = 0 if _needs_maintenance(seg) else 1
    load = max(
        float(getattr(seg, "load_curva", 0.0) or 0.0),
        float(getattr(seg, "load_tangente", 0.0) or 0.0),
    )
    return (urgent, -load, seg.name)


def _perform_next_step(sim: Simulator) -> bool:
    """Execute one simulation step (move or wait).

    Args:
        sim: Simulator instance.

    Returns:
        True if step was successful, False if no valid moves.
    """
    if _segments_already_due(sim):
        options = sim.get_possible_moves()
        if not options:
            turned = False
            if sim.current_station and sim.current_station.can_turn:
                turned = sim.flip_global_direction()
            if turned:
                return True
            options = sim.get_all_moves_any_direction()
            if not options:
                return False
        seg, next_station = sorted(options, key=_move_priority)[0]
        action = _maintenance_action_for(seg) if _needs_maintenance(seg) else ACTION_MOVE
        sim.move_to(seg, next_station, action=action)
        return True

    wait_days = _days_until_next_threshold(sim)
    if wait_days <= 0:
        if sim.daily_map:
            wait_days = 1
        else:
            return False
    return bool(sim.wait_days(wait_days))


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


def run_auto_plan(config: AutoPlanConfig) -> AutoPlanResult:
    sim = _init_simulation(config)
    limit_date = datetime(config.end_year, 12, 31)
    stop_reason = "steps_limit"
    for _ in range(config.steps):
        progressed = _perform_next_step(sim)
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
    return AutoPlanResult(simulator=sim, stop_reason=stop_reason, stop_details=stop_details_for_result)


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
