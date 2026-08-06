"""Helpers to load station/segment definitions from JSON network configs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.models import Segment, Station


@dataclass(slots=True)
class NetworkMetadata:
    """Network metadata - kept for backward compatibility but no longer used."""
    pass


@dataclass(slots=True)
class NetworkLayout:
    mode: str = "table"
    table_overrides: Dict[str, Dict[str, float]] = field(default_factory=dict)
    scale: float = 1.0


@dataclass(slots=True)
class NetworkConfig:
    name: str
    stations: Dict[str, Station]
    segments: List[Segment]
    metadata: NetworkMetadata
    layout: NetworkLayout
    timeline_order: List[str] = field(default_factory=list)


class NetworkConfigError(ValueError):
    """Raised when a network JSON file is missing required fields."""


_REQUIRED_STATION_FIELDS = {"name"}
_REQUIRED_SEGMENT_FIELDS = {"name", "start", "end", "length_km", "mtbt_threshold_curva", "mtbt_threshold_tangente", "move_time_days", "maintenance_time_days"}


def _validate_mapping(payload: Mapping[str, Any], *, path: Path) -> None:
    """Validate network JSON payload contains required top-level keys.

    Args:
        payload: Parsed JSON dictionary.
        path: File path for error messages.

    Raises:
        NetworkConfigError: If required keys are missing.
    """
    if "stations" not in payload or "segments" not in payload:
        missing_keys = []
        if "stations" not in payload:
            missing_keys.append("'stations'")
        if "segments" not in payload:
            missing_keys.append("'segments'")
        raise NetworkConfigError(
            f"Network file {path.name} is missing required top-level keys: {', '.join(missing_keys)}. "
            "A valid network file must contain 'stations' and 'segments' arrays."
        )


def _load_json(path: Path) -> Dict[str, Any]:
    """Load and parse network JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed JSON dictionary.

    Raises:
        NetworkConfigError: If file not found, invalid JSON, or not a dict.
    """
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NetworkConfigError(
            f"Network file not found: {path.name}. "
            f"Searched in: {path.parent}. "
            "Ensure the file exists and the path is correct."
        ) from exc
    except json.JSONDecodeError as exc:
        raise NetworkConfigError(
            f"Network file {path.name} contains invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}. "
            "Check the file for syntax errors like missing commas, brackets, or quotes."
        ) from exc
    if not isinstance(payload, dict):
        raise NetworkConfigError(
            f"Network file {path.name} must contain a JSON object at the top level, not {type(payload).__name__}. "
            "The file should start with '{' and end with '}'."
        )
    return payload


def _build_stations(station_entries: Iterable[Mapping[str, Any]]) -> Dict[str, Station]:
    """Build station objects from JSON entries.

    Args:
        station_entries: Iterable of station definition dictionaries.

    Returns:
        Dictionary mapping station names to Station objects.

    Raises:
        NetworkConfigError: If entries are invalid or contain duplicates.
    """
    stations: Dict[str, Station] = {}
    for entry in station_entries:
        if not isinstance(entry, dict) or not _REQUIRED_STATION_FIELDS.issubset(entry):
            raise NetworkConfigError(
                "Each station entry must be a dictionary with at least a 'name' field. "
                f"Found entry: {entry}"
            )
        name = str(entry["name"]).strip()
        if not name:
            raise NetworkConfigError(
                "Station names cannot be blank or whitespace-only. "
                "Each station must have a valid name."
            )
        if name in stations:
            raise NetworkConfigError(
                f"Duplicate station name detected: '{name}'. "
                "Each station must have a unique name in the network."
            )
        can_turn = bool(entry.get("can_turn", False))
        station = Station(name=name, can_turn=can_turn)
        stations[name] = station
    return stations


def _build_segments(
    segment_entries: Iterable[Mapping[str, Any]],
    stations: Dict[str, Station],
) -> List[Segment]:
    """Build segment objects from JSON entries.

    Args:
        segment_entries: Iterable of segment definition dictionaries.
        stations: Dictionary of available stations.

    Returns:
        List of Segment objects.

    Raises:
        NetworkConfigError: If entries are invalid or reference unknown stations.
    """
    segments: List[Segment] = []
    for entry in segment_entries:
        if not isinstance(entry, dict) or not _REQUIRED_SEGMENT_FIELDS.issubset(entry):
            missing = _REQUIRED_SEGMENT_FIELDS - set(entry or {})
            raise NetworkConfigError(
                f"Segment entry is invalid or missing required fields: {missing}. "
                f"Required: {_REQUIRED_SEGMENT_FIELDS}. Found entry: {entry}"
            )
        start = stations.get(entry["start"])
        end = stations.get(entry["end"])
        if not start or not end:
            raise NetworkConfigError(
                f"Segment '{entry['name']}' references unknown station(s): "
                f"start='{entry['start']}', end='{entry['end']}'. "
                f"Available stations: {', '.join(sorted(stations.keys()))}. "
                "Ensure all station names match exactly."
            )
        allowed = entry.get("allowed_movements") or []
        cleaned_allowed: List[Tuple[str, str]] = []
        for move in allowed:
            if not isinstance(move, Sequence) or isinstance(move, (str, bytes)) or len(move) != 2:
                continue
            src, dst = move
            cleaned_allowed.append((str(src), str(dst)))
        if not cleaned_allowed:
            cleaned_allowed = [
                (start.name, end.name),
                (end.name, start.name),
            ]
        segment = Segment(
            name=str(entry["name"]),
            start_station=start,
            end_station=end,
            length=float(entry["length_km"]),
            mtbt_threshold_curva=float(entry["mtbt_threshold_curva"]),
            mtbt_threshold_tangente=float(entry["mtbt_threshold_tangente"]),
            move_time_days=int(entry["move_time_days"]),
            maintenance_time_days=int(entry["maintenance_time_days"]),
            allowed_movements=cleaned_allowed,
            curve_length_km=float(entry.get("curve_length_km", 0.0) or 0.0),
            tangent_length_km=float(entry.get("tangent_length_km", 0.0) or 0.0),
            move_billed_days=float(entry.get("move_billed_days", 0.0) or 0.0),
            maintenance_billed_days=float(entry.get("maintenance_billed_days", 0.0) or 0.0),
        )
        segments.append(segment)
    return segments


def _parse_layout(payload: Optional[Mapping[str, Any]]) -> NetworkLayout:
    if not isinstance(payload, dict):
        return NetworkLayout()
    raw_overrides = payload.get("table_overrides") or payload.get("overrides") or {}
    overrides: Dict[str, Dict[str, float]] = {}
    if isinstance(raw_overrides, dict):
        for name, coords in raw_overrides.items():
            if not isinstance(coords, dict):
                continue
            x_raw = coords.get("x")
            y_raw = coords.get("y")
            if x_raw is None or y_raw is None:
                continue
            try:
                x_val = float(x_raw)
                y_val = float(y_raw)
            except (TypeError, ValueError):
                continue
            overrides[str(name)] = {"x": x_val, "y": y_val}
    mode = str(payload.get("mode", "table") or "table").lower()
    if mode not in {"table", "auto"}:
        mode = "table"
    scale_val = payload.get("scale", 1.0)
    try:
        scale = float(scale_val)
    except (TypeError, ValueError):
        scale = 1.0
    return NetworkLayout(mode=mode, table_overrides=overrides, scale=scale)


def load_network(path: Path) -> NetworkConfig:
    payload = _load_json(path)
    _validate_mapping(payload, path=path)
    raw_stations = payload["stations"]
    raw_segments = payload["segments"]
    if not isinstance(raw_stations, list) or not isinstance(raw_segments, list):
        raise NetworkConfigError("Network file must define 'stations' and 'segments' as arrays.")
    stations = _build_stations(raw_stations)
    segments = _build_segments(raw_segments, stations)
    
    # Metadata kept for backward compatibility
    metadata = NetworkMetadata()
    
    layout = _parse_layout(payload.get("layout"))
    raw_order = payload.get("timeline_order")
    timeline_order: List[str] = []
    if isinstance(raw_order, list):
        timeline_order = [str(s) for s in raw_order if s]
    return NetworkConfig(
        name=str(payload.get("name", path.stem)),
        stations=stations,
        segments=segments,
        metadata=metadata,
        layout=layout,
        timeline_order=timeline_order,
    )


def list_network_files(base_dir: Path) -> Dict[str, Path]:
    base_dir = base_dir.expanduser().resolve()
    if not base_dir.exists():
        return {}
    mapping: Dict[str, Path] = {}
    for json_path in base_dir.glob("*.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                name = str(data.get("name", json_path.stem))
            else:
                name = json_path.stem
        except Exception:
            name = json_path.stem
        mapping[name] = json_path
    return mapping
