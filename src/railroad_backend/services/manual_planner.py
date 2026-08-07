"""Manual planning helpers built on top of the simulator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

from src.models import ACTION_MOVE
from railroad_backend.domain.simulator import DEFAULT_NETWORK_FILE, Simulator
from railroad_backend.domain.validation import validate_manual_plan

from .auto_planner import initialize_simulation_from_args
from .network_editor import (
    default_facing_station_from_config,
    default_start_station_from_config,
)

if TYPE_CHECKING:
    from src.utils.network_loader import NetworkConfig


@dataclass(frozen=True)
class ManualPlanConfig:
    csv_path: Path
    start_station: str
    facing_station: str
    start_year: int
    end_year: int
    second_kld: bool
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


@dataclass(frozen=True)
class ManualPlanReplay:
    simulator: Simulator
    errors: List[str]


@dataclass(frozen=True)
class ManualMoveOption:
    segments: Tuple[str, ...]
    destination: str
    maintenance_aligned: bool


def _find_segments_for_move(sim: Simulator, segment_names: Sequence[str], destination: str):
    """Locate the segment tuple matching segment_names that connects the
    current station to destination.

    Args:
        sim: Simulator instance.
        segment_names: Names of the segments to traverse, in the order
            returned by get_possible_moves()/get_all_moves_any_direction()
            (Singela first when present, directional last).
        destination: Name of destination station.

    Returns:
        Tuple of Segment objects (same order as segment_names) or None if
        no matching option is currently available.
    """
    for segments, station in sim.get_all_moves_any_direction():
        if station.name != destination:
            continue
        if tuple(s.name for s in segments) == tuple(segment_names):
            return segments
    return None


def _handle_turn_step(simulator: Simulator, step_idx: int) -> Optional[str]:
    """Execute a turn step.

    Args:
        simulator: Active simulator instance.
        step_idx: Current step index for error messages.

    Returns:
        Error message if step failed, None if successful.
    """
    if not simulator.flip_global_direction():
        return f"Step {step_idx}: current station cannot turn."
    return None


def _handle_wait_step(simulator: Simulator, step: Dict[str, Any], step_idx: int) -> Optional[str]:
    """Execute a wait step.

    Args:
        simulator: Active simulator instance.
        step: Step definition with wait duration.
        step_idx: Current step index for error messages.

    Returns:
        Error message if step failed, None if successful.
    """
    wait_days = int(step.get("days", 0))
    if wait_days <= 0:
        return f"Step {step_idx}: wait duration must be at least 1 day."
    if not simulator.wait_days(wait_days):
        return f"Step {step_idx}: unable to idle for {wait_days} day(s)."
    return None


def _handle_move_step(simulator: Simulator, step: Dict[str, Any], step_idx: int) -> Optional[str]:
    """Execute a move or maintenance step.

    Args:
        simulator: Active simulator instance.
        step: Step definition with segment and destination.
        step_idx: Current step index for error messages.

    Returns:
        Error message if step failed, None if successful.
    """
    dest_name = step.get("destination")  # Changed from next_station
    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]  # plans saved before the corridor change
    if not dest_name or not segment_names:
        return f"Step {step_idx}: incomplete move definition."

    destination = simulator.stations.get(dest_name)
    if destination is None:
        return f"Step {step_idx}: destination {dest_name} is unknown."

    segments = _find_segments_for_move(simulator, segment_names, dest_name)
    if segments is None:
        current = simulator.current_station.name if simulator.current_station else "unknown"
        return f"Step {step_idx}: segment(s) {segment_names} cannot reach {dest_name} from {current}."

    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    maintain_segment_names = step.get("maintain_segments")
    maintain_segments = (
        tuple(s for s in segments if s.name in maintain_segment_names)
        if maintain_segment_names is not None
        else None
    )
    try:
        simulator.move_to(segments, destination, action=action_code, duration_override=duration_override, maintain_segments=maintain_segments)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Manual plan step %d failed: %s", step_idx, exc)
        return f"Step {step_idx}: failed to execute ({exc})."
    return None


def replay_manual_plan(config: ManualPlanConfig, plan: Sequence[Dict[str, Any]]) -> ManualPlanReplay:
    # Validate plan structure first
    structural_errors = validate_manual_plan(list(plan))
    if structural_errors:
        # Return simulator with empty state if plan structure is invalid
        network_ref = config.network_source or str(DEFAULT_NETWORK_FILE)
        sim = Simulator(network_ref)
        return ManualPlanReplay(simulator=sim, errors=structural_errors)
    
    simulator = initialize_simulation_from_args(
        config.csv_path,
        start_station=config.start_station,
        facing_station=config.facing_station,
        start_year=config.start_year,
        end_year=config.end_year,
        second_kld=config.second_kld,
        network_source=config.network_source,
    )
    errors: List[str] = []
    for idx, step in enumerate(plan, start=1):
        mode = step.get("mode")
        error: Optional[str] = None

        if mode == "turn":
            error = _handle_turn_step(simulator, idx)
        elif mode == "wait":
            error = _handle_wait_step(simulator, step, idx)
        else:
            error = _handle_move_step(simulator, step, idx)

        if error:
            errors.append(error)
            break

    return ManualPlanReplay(simulator=simulator, errors=errors)


def list_available_moves(sim: Simulator) -> List[ManualMoveOption]:
    """List all possible moves from current position.

    Args:
        sim: Simulator instance.

    Returns:
        List of ManualMoveOption sorted by alignment and destination.
    """
    aligned_pairs = {
        (tuple(seg.name for seg in segments), dest.name)
        for segments, dest in sim.get_possible_moves()
    }
    options: List[ManualMoveOption] = []
    seen = set()
    for segments, dest in sim.get_all_moves_any_direction():
        names = tuple(seg.name for seg in segments)
        key = (names, dest.name)
        if key in seen:
            continue
        seen.add(key)
        options.append(ManualMoveOption(segments=names, destination=dest.name, maintenance_aligned=key in aligned_pairs))
    options.sort(key=lambda item: (0 if item.maintenance_aligned else 1, item.destination))
    return options


def manual_defaults(config: "NetworkConfig") -> Dict[str, Any]:
    """Get default configuration values for manual planning.

    Args:
        config: Network configuration.

    Returns:
        Dictionary with start_station, facing_station, years, and equipment settings.
    """
    start_station = default_start_station_from_config(config)
    return {
        "start_station": start_station,
        "facing_station": default_facing_station_from_config(config, start_station),
        "start_year": 2025,
        "end_year": 2026,
        "second_kld": False,
    }


__all__ = [
    "ManualPlanConfig",
    "ManualPlanReplay",
    "ManualMoveOption",
    "replay_manual_plan",
    "list_available_moves",
    "manual_defaults",
]
