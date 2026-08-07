"""Core Simulator class for railroad maintenance simulation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE, VALID_ACTIONS, GrinderMachine, Segment, Station
from src.utils.network_loader import NetworkConfig
from src.simulator.direction_model import _direction_model_from_segments
from src.simulator.network_utils import (
    _get_possible_moves,
    _get_turn_choices,
    _resolve_network,
    build_network,
)

DailyMap = Dict[str, Dict[str, float]]


_CARREGADO_SUFFIXES = ("-LP", "-C")
_VAZIO_SUFFIXES = ("-LD", "-V")


def _classify_directional_segment(segment: Segment, from_station_name: str) -> Optional[str]:
    """CARREGADO/VAZIO for a single segment.

    A unidirectional segment (LP/Carregado or LD/Vazio) only ever has one
    legal travel direction — its own start station — so classifying it by
    "am I departing from its start" always returns CARREGADO, never VAZIO,
    regardless of which physical direction (import/export) it actually
    represents. LP is always Carregado and LD is always Vazio by identity,
    not by which way you currently happen to be facing, so the segment's own
    name suffix (the established convention across every network file) is
    checked first. Only falls back to the start/end heuristic for segments
    without that suffix — the Singela (bidirectional, ida=Carregado/
    volta=Vazio is a meaningful distinction there) and plain single-segment
    corridors (e.g. the simplified default.json test network).
    """
    if segment.name.endswith(_CARREGADO_SUFFIXES):
        return "CARREGADO"
    if segment.name.endswith(_VAZIO_SUFFIXES):
        return "VAZIO"
    if segment.start_station.name == from_station_name:
        return "CARREGADO"
    if segment.end_station.name == from_station_name:
        return "VAZIO"
    return None


class Simulator:
    """Programmatic simulator used by Streamlit and tests."""

    def __init__(self, network: Optional[Union[NetworkConfig, str, Path]] = None) -> None:
        self.stations: Dict[str, Station] = {}
        self.segments: List[Segment] = []
        self._network = _resolve_network(network)
        self._build_network()
        self._direction_model = _direction_model_from_segments(self.segments)

        self.machine: Optional[GrinderMachine] = None
        self.simulation_date: Optional[datetime] = None
        self.previous_station: Optional[Station] = None
        self.current_station: Optional[Station] = None

        self.daily_map: Optional[DailyMap] = None

        self.steps: List[Dict[str, object]] = []
        self.movement_days_total = 0
        self.maintenance_days_total = 0
        self.maintenance_count = 0
        self.idle_days_total = 0
        self.maintenance_log: List[Tuple[str, Optional[str], int]] = []
        self.stop_reason: str = ""
        self.stop_details: Dict[str, object] = {}

    def _build_network(self) -> None:
        self.stations, self.segments = build_network(self._network)
        self._direction_model = _direction_model_from_segments(self.segments)

    def init_machine(
        self,
        start_station_name: str = "TRO",
        facing_station_name: str = "TMI",
        start_date: Optional[datetime] = None,
        start_year: Optional[int] = None,
        second_kld_installed: bool = False,
        daily_map: Optional[DailyMap] = None,
    ) -> None:
        """Initialize the grinder machine state for simulation.

        Args:
            start_station_name: Name of station where machine begins.
            facing_station_name: Name of station the machine initially faces.
            start_date: Simulation start date. Takes precedence over start_year.
            start_year: Simulation start year (defaults to January 1st).
            second_kld_installed: Whether second KLD equipment is installed.
            daily_map: Optional pre-built daily MTBT accumulation map.

        Raises:
            ValueError: If start_year is provided and is negative or invalid.
            TypeError: If arguments have incorrect types.
        """
        if not isinstance(start_station_name, str):
            raise TypeError(f"start_station_name must be str, got {type(start_station_name).__name__}")
        if not isinstance(facing_station_name, str):
            raise TypeError(f"facing_station_name must be str, got {type(facing_station_name).__name__}")
        if start_date is not None and not isinstance(start_date, datetime):
            raise TypeError(f"start_date must be datetime or None, got {type(start_date).__name__}")
        if start_year is not None:
            if not isinstance(start_year, int):
                raise TypeError(f"start_year must be int or None, got {type(start_year).__name__}")
            if start_year < 1900 or start_year > 2200:
                raise ValueError(f"start_year must be between 1900-2200, got {start_year}")
        if not isinstance(second_kld_installed, bool):
            raise TypeError(f"second_kld_installed must be bool, got {type(second_kld_installed).__name__}")

        if start_station_name not in self.stations:
            start_station_name = "TRO"
        if facing_station_name not in self.stations:
            facing_station_name = "TMI"

        start_segment = None
        initial_dir = "forward"
        for seg in self.segments:
            if seg.start_station.name == start_station_name and seg.end_station.name == facing_station_name:
                start_segment = seg
                initial_dir = "forward"
                break
            if seg.end_station.name == start_station_name and seg.start_station.name == facing_station_name:
                start_segment = seg
                initial_dir = "reverse"
                break
        if not start_segment:
            start_segment = self.segments[0]
            facing_station_name = start_segment.end_station.name

        init_global = self._classify_station_pair(start_station_name, facing_station_name) or "CARREGADO"
        self.machine = GrinderMachine(
            front_car_position=start_segment,
            rear_car_position=start_segment,
            direction=initial_dir,
            facing=("Carregado" if init_global == "CARREGADO" else "Vazio"),
            global_direction=init_global,
            second_kld_installed=second_kld_installed,
        )

        if start_date:
            self.simulation_date = start_date
        elif start_year:
            self.simulation_date = datetime(start_year, 1, 1)
        else:
            self.simulation_date = datetime.now()

        self.daily_map = daily_map
        self.current_station = self.stations[start_station_name]
        self.previous_station = None

    def get_possible_moves(self) -> List[Tuple[Tuple[Segment, ...], Station]]:
        station = self.current_station
        if station is None:
            return []
        pairs = _get_possible_moves(self.segments, station)
        machine = self.machine
        if not machine:
            return pairs
        filtered = []
        for segments, other in pairs:
            directional = segments[-1]
            edge_dir = _classify_directional_segment(directional, station.name)
            if edge_dir is None or edge_dir == machine.global_direction:
                filtered.append((segments, other))
        return filtered

    def get_all_moves_any_direction(self) -> List[Tuple[Tuple[Segment, ...], Station]]:
        station = self.current_station
        if station is None:
            return []
        return _get_possible_moves(self.segments, station)

    def get_turn_choices(self) -> List[Station]:
        station = self.current_station
        if station is None:
            return []
        return _get_turn_choices(self.segments, station, self.previous_station)

    def flip_global_direction(self) -> bool:
        station = self.current_station
        machine = self.machine
        simulation_date = self.simulation_date
        if not station or not station.can_turn:
            return False
        if machine is None or simulation_date is None:
            return False
        machine.global_direction = "VAZIO" if machine.global_direction == "CARREGADO" else "CARREGADO"
        machine.facing = "Carregado" if machine.global_direction == "CARREGADO" else "Vazio"
        start = simulation_date
        duration = 1
        self._apply_daily_mtbt_for_period(duration)
        end_time = self.simulation_date
        if end_time is None:
            return False
        self.movement_days_total += duration
        self.steps.append(
            {
                "segment": station.name,
                "action": "turn",
                "facing": machine.facing,
                "mtbt_before": None,
                "days": duration,
                "start": start.strftime("%Y-%m-%d"),
                "end": end_time.strftime("%Y-%m-%d"),
            }
        )
        return True

    def _apply_daily_mtbt_for_period(self, days: int) -> None:
        if days <= 0 or self.simulation_date is None:
            return
        if self.daily_map:
            # Cache segment daily values to avoid repeated dict lookups
            seg_daily_vals = [(seg, self.daily_map.get(seg.name)) for seg in self.segments]
            for day_offset in range(days):
                date_str = (self.simulation_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                for seg, vals in seg_daily_vals:
                    if vals:
                        val = vals.get(date_str)
                        if val:
                            try:
                                seg.add_mtbt(float(val))
                            except (TypeError, ValueError) as exc:
                                logger.debug("Skipping MTBT value for %s on %s: %s", seg.name, date_str, exc)
        self.simulation_date += timedelta(days=days)

    def turn_to(self, station_name: str) -> bool:  # pragma: no cover (legacy signature)
        del station_name
        return self.flip_global_direction()

    def _apply_arrival_facing_logic(self) -> None:
        if not self.machine:
            return
        self.machine.facing = "Carregado" if self.machine.global_direction == "CARREGADO" else "Vazio"

    def wait_days(self, days: int) -> bool:
        """Wait for specified number of days without moving.

        Args:
            days: Number of days to wait.

        Returns:
            True if wait was successful.

        Raises:
            TypeError: If days is not an integer.
            ValueError: If days is less than 1.
        """
        if not isinstance(days, int):
            raise TypeError(f"days must be int, got {type(days).__name__}")
        if days < 1:
            raise ValueError(f"days must be at least 1, got {days}")

        simulation_date = self.simulation_date
        if simulation_date is None:
            return False
        start = simulation_date
        self._apply_daily_mtbt_for_period(days)
        end_time = self.simulation_date
        if end_time is None:
            return False
        self.idle_days_total += days
        self.steps.append(
            {
                "segment": self.current_station.name if self.current_station else "",
                "action": "wait",
                "facing": self.machine.facing if self.machine else None,
                "mtbt_before": None,
                "days": days,
                "start": start.strftime("%Y-%m-%d"),
                "end": end_time.strftime("%Y-%m-%d"),
            }
        )
        return True

    def move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None, maintain_segments: Optional[Sequence[Segment]] = None) -> Dict[str, object]:
        """Execute a move or maintenance action on one or more segments.

        Args:
            segments: Target segment (or segments — Singela + directional
                LP/LD leg, when the corridor has one) to traverse or
                maintain. A bare Segment is treated as a 1-element sequence.
            next_station: Destination station.
            action: Action type — use ACTION_MAINTAIN or ACTION_MOVE constants.
                Legacy single-char values 'm' and 'v' are also accepted.

        Returns:
            Dictionary with step details.

        Raises:
            RuntimeError: If simulator not initialized.
            TypeError: If arguments have incorrect types.
            ValueError: If action is invalid or stations don't match segment.
        """
        if isinstance(segments, Segment):
            segments = (segments,)
        else:
            try:
                segments = tuple(segments)
            except TypeError:
                raise TypeError(f"segments must be a Segment or a sequence of Segment, got {type(segments).__name__}")
        if not segments or not all(isinstance(s, Segment) for s in segments):
            raise TypeError(f"segments must contain only Segment instances, got {[type(s).__name__ for s in segments]!r}")
        if not isinstance(next_station, Station):
            raise TypeError(f"next_station must be Station, got {type(next_station).__name__}")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(VALID_ACTIONS)!r}, got {action!r}")
        # Normalise legacy single-char codes to canonical names
        if action == "m":
            action = ACTION_MAINTAIN
        elif action == "v":
            action = ACTION_MOVE

        # seg is the directional/most-specific segment (last in the tuple, see
        # _get_possible_moves) -- it's the one that determines endpoints,
        # direction classification, and the machine's resting position.
        seg = segments[-1]
        # Validate next_station is an endpoint of seg
        if next_station not in (seg.start_station, seg.end_station):
            raise ValueError(
                f"next_station '{next_station.name}' is not an endpoint of segment '{seg.name}'. "
                f"Valid endpoints: '{seg.start_station.name}', '{seg.end_station.name}'"
            )

        current_station = self.current_station
        machine = self.machine
        simulation_date = self.simulation_date
        if current_station is None or machine is None or simulation_date is None:
            raise RuntimeError(
                "Simulator must be initialized with init_machine() before executing moves. "
                "Call sim.init_machine(start_station_name, facing_station_name, start_year=YYYY) first."
            )
        if (current_station.name, next_station.name) not in getattr(seg, "allowed_movements", []):
            for candidate in self.segments:
                if (
                    (candidate.start_station == current_station and candidate.end_station == next_station)
                    or (candidate.end_station == current_station and candidate.start_station == next_station)
                ) and (current_station.name, next_station.name) in getattr(candidate, "allowed_movements", []):
                    seg = candidate
                    break

        edge_dir = _classify_directional_segment(seg, current_station.name)
        movement_dir = "forward" if edge_dir == machine.global_direction else "reverse"
        machine.direction = movement_dir
        machine.front_car_position = seg

        mtbt_before_curva = getattr(seg, "load_curva", None)
        mtbt_before_tangente = getattr(seg, "load_tangente", None)

        maintained: Tuple[Segment, ...] = ()
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            maintain_set = list(maintain_segments) if maintain_segments is not None else list(segments)
            if machine.second_kld_installed or edge_dir == machine.global_direction:
                for component_seg in segments:
                    if component_seg in maintain_set:
                        machine.perform_maintenance(component_seg, component=component)
                maintained = tuple(s for s in segments if s in maintain_set)
                performed = True

        if performed:
            duration = duration_override if duration_override is not None else sum(
                s.maintenance_time_days if s in maintained else s.move_time_days for s in segments
            )
            self.maintenance_days_total += duration
            self.maintenance_count += 1
            self.maintenance_log.append((seg.name, None, duration))
        else:
            duration = duration_override if duration_override is not None else sum(s.move_time_days for s in segments)
            self.movement_days_total += duration
            if not self.daily_map:
                for component_seg in segments:
                    component_seg.increment_mtbt()

        start = simulation_date
        self._apply_daily_mtbt_for_period(duration)
        end_time = self.simulation_date
        if end_time is None:
            raise RuntimeError("Simulation date unavailable after move")

        self.steps.append(
            {
                "segment": seg.name,
                "segments": [s.name for s in segments],
                "maintained_segments": [s.name for s in maintained],
                "action": (
                    "maintenance"
                    if action == ACTION_MAINTAIN and performed
                    else "maintenance_failed"
                    if action == ACTION_MAINTAIN
                    else "maintenance_curves"
                    if action == ACTION_MAINTAIN_CURVES and performed
                    else "maintenance_curves_failed"
                    if action == ACTION_MAINTAIN_CURVES
                    else "move"
                ),
                "facing": machine.facing,
                "mtbt_before_curva": float(mtbt_before_curva) if isinstance(mtbt_before_curva, (int, float)) else mtbt_before_curva,
                "mtbt_before_tangente": float(mtbt_before_tangente) if isinstance(mtbt_before_tangente, (int, float)) else mtbt_before_tangente,
                "days": duration,
                "start": start.strftime("%Y-%m-%d"),
                "end": end_time.strftime("%Y-%m-%d"),
            }
        )

        for idx, entry in enumerate(self.maintenance_log):
            if entry[0] == seg.name and entry[1] is None:
                self.maintenance_log[idx] = (entry[0], end_time.strftime("%Y-%m-%d"), entry[2])

        self.previous_station = current_station
        self.current_station = next_station
        self._apply_arrival_facing_logic()

        return {"performed": performed, "duration": duration}

    def _classify_station_pair(self, a_name: str, b_name: str) -> Optional[str]:
        """CARREGADO/VAZIO for traveling a_name -> b_name, resolved the same
        way a move option is (see _get_possible_moves): among every segment
        that allows this exact direction, the most specific one (a
        directional LP/LD/Carregado/Vazio leg, when present) determines the
        classification. Used by init_machine() and classify_edge_direction()
        so the initial facing and every later move agree.
        """
        matching = [seg for seg in self.segments if (a_name, b_name) in seg.allowed_movements]
        if not matching:
            return None
        matching.sort(key=lambda seg: len(seg.allowed_movements), reverse=True)
        return _classify_directional_segment(matching[-1], a_name)

    def classify_edge_direction(self, start_station: str, end_station: str) -> Optional[str]:
        """Expose the simulator's direction classification for tests and tooling."""
        return self._classify_station_pair(start_station, end_station)


__all__ = ["Simulator", "DailyMap"]
