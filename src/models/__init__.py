"""Dataclass-based models shared between the simulator and services."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union


Movement = Tuple[str, str]
Position = Union["Segment", "Station"]

# Action constants for move_to() — use these instead of bare string literals.
ACTION_MAINTAIN = "maintain"
ACTION_MAINTAIN_CURVES = "maintain_curves"
ACTION_MOVE = "move"
# Legacy single-char aliases kept for backward compatibility with stored plans.
_LEGACY_ACTION_MAINTAIN = "m"
_LEGACY_ACTION_MOVE = "v"
# All valid action values accepted by Simulator.move_to()
VALID_ACTIONS = frozenset({ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE, _LEGACY_ACTION_MAINTAIN, _LEGACY_ACTION_MOVE})


@dataclass(slots=True)
class Station:
    """Railroad station node with optional turning capability."""

    name: str
    can_turn: bool = False
    segments: List["Segment"] = field(default_factory=list)

    def add_segment(self, segment: "Segment") -> None:
        if segment not in self.segments:
            self.segments.append(segment)

    def __repr__(self) -> str:
        # Station <-> Segment hold circular references (segments back-reference
        # their stations); the default dataclass repr recurses through the whole
        # network graph with no memoization, which is combinatorially explosive
        # on anything but a tiny network. Keep this shallow.
        return f"Station(name={self.name!r}, can_turn={self.can_turn}, segments={len(self.segments)})"


@dataclass(slots=True)
class Segment:
    """Directed edge between two stations with MTBT tracking."""

    name: str
    start_station: Station
    end_station: Station
    length: float = 0.0
    load: float = 0.0
    maintenance_due: bool = False
    mtbt_threshold: float = 0.0
    allowed_movements: List[Movement] = field(default_factory=list)
    move_time_days: int = 1
    maintenance_time_days: int = 1
    curve_length_km: float = 0.0
    tangent_length_km: float = 0.0
    move_billed_days: float = 0.0
    maintenance_billed_days: float = 0.0

    def __repr__(self) -> str:
        # See Station.__repr__: avoid recursing into start_station/end_station,
        # which each hold a back-reference to their full segment list.
        return (
            f"Segment(name={self.name!r}, start={self.start_station.name!r}, "
            f"end={self.end_station.name!r}, length={self.length})"
        )

    def __post_init__(self) -> None:
        if not self.allowed_movements:
            self.allowed_movements = [
                (self.start_station.name, self.end_station.name),
                (self.end_station.name, self.start_station.name),
            ]
        else:
            cleaned: List[Movement] = []
            for pair in self.allowed_movements:
                if (
                    not isinstance(pair, Sequence)
                    or isinstance(pair, (str, bytes))
                    or len(pair) != 2
                ):
                    continue
                src, dst = pair
                cleaned.append((str(src), str(dst)))
            self.allowed_movements = cleaned or [
                (self.start_station.name, self.end_station.name),
                (self.end_station.name, self.start_station.name),
            ]
        self.start_station.add_segment(self)
        self.end_station.add_segment(self)

    def add_load(self, amount: float) -> None:
        """Add an MTBT amount and update maintenance flag when threshold is reached."""

        try:
            self.load += float(amount)
        except (TypeError, ValueError):  # fall back for Decimal/np types lacking float protocol
            self.load += amount  # type: ignore[operator]
        if self.mtbt_threshold and self.load >= self.mtbt_threshold:
            self.maintenance_due = True

    def reset_maintenance(self) -> None:
        self.load = 0.0
        self.maintenance_due = False

    def increment_mtbt(self) -> None:
        self.add_load(1.0)

    def add_mtbt(self, amount: float) -> None:
        self.add_load(amount)


@dataclass(slots=True)
class GrinderMachine:
    """Stateful grinder used by the simulator to move through the network."""

    front_car_position: Position
    rear_car_position: Position
    direction: str = "forward"
    mode: str = "move"
    facing: Optional[str] = None
    global_direction: Optional[str] = None
    second_kld_installed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.global_direction, str):
            self.global_direction = self.global_direction.upper()

    def move(self, next_front_position: Position, next_rear_position: Position, direction: Optional[str] = None) -> None:
        self.front_car_position = next_front_position
        self.rear_car_position = next_rear_position
        if direction:
            self.direction = direction
        self.mode = "move"

    def perform_maintenance(self, segment: Segment) -> bool:
        if hasattr(segment, "reset_maintenance"):
            segment.reset_maintenance()
            self.mode = "maintenance"
            return True
        return False


__all__ = [
    "GrinderMachine",
    "Segment",
    "Station",
    "ACTION_MAINTAIN",
    "ACTION_MAINTAIN_CURVES",
    "ACTION_MOVE",
    "VALID_ACTIONS",
]