"""Network helper functions for adjacency and movement logic."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from src.models import Segment, Station
from src.utils.network_loader import NetworkConfig, load_network

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETWORK_FILE = PROJECT_ROOT / "data" / "networks" / "default.json"
_DEFAULT_CONFIG = load_network(DEFAULT_NETWORK_FILE)


def _get_adjacent(segments: List[Segment], station: Station) -> Tuple[List[Segment], List[Station]]:
    """Return segments and stations adjacent to the given station.

    Args:
        segments: List of all network segments.
        station: Station to find neighbors for.

    Returns:
        Tuple of (adjacent_segments, adjacent_stations).
    """
    adjacent_segments: List[Segment] = []
    adjacent_stations: List[Station] = []
    for seg in segments:
        if seg.start_station == station:
            adjacent_segments.append(seg)
            adjacent_stations.append(seg.end_station)
        elif seg.end_station == station:
            adjacent_segments.append(seg)
            adjacent_stations.append(seg.start_station)
    return adjacent_segments, adjacent_stations


def _get_possible_moves(segments: List[Segment], station: Station) -> List[Tuple[Tuple[Segment, ...], Station]]:
    """Return list of (segment_tuple, other_station) for each reachable neighbor.

    Every segment whose `allowed_movements` covers this exact direction is
    included in the tuple, ordered with the most specific segment last
    (`len(allowed_movements) == 1`, i.e. a directional LP/LD/Carregado/Vazio
    segment) — most-restrictive-last means the caller can always treat
    `segment_tuple[-1]` as "the segment nearest the destination". Where a
    station pair has a Singela shared trunk plus a directional LP/LD leg,
    both come back together in one tuple (a single logical move); where
    there's no Singela (plain Carregado/Vazio pair, or an ordinary single
    segment), the tuple has exactly 1 element, unchanged from before.

    Args:
        segments: List of all network segments.
        station: Current station to find valid moves from.

    Returns:
        List of (segment_tuple, destination_station) tuples for legal moves.
    """
    adjacent_segments, adjacent_stations = _get_adjacent(segments, station)
    by_destination: Dict[str, List[Segment]] = {}
    destination_station_by_name: Dict[str, Station] = {}
    for seg, other in zip(adjacent_segments, adjacent_stations):
        by_destination.setdefault(other.name, []).append(seg)
        destination_station_by_name[other.name] = other

    possible: List[Tuple[Tuple[Segment, ...], Station]] = []
    for other_name, candidates in by_destination.items():
        matching = [
            seg for seg in candidates
            if (station.name, other_name) in seg.allowed_movements
        ]
        if not matching:
            continue
        matching.sort(key=lambda seg: len(seg.allowed_movements), reverse=True)
        possible.append((tuple(matching), destination_station_by_name[other_name]))
    return possible


def _get_turn_choices(
    segments: List[Segment],
    current_station: Station,
    previous_station: Optional[Station],
) -> List[Station]:
    """Return up to two stations to face when turning at current_station.

    Args:
        segments: List of all network segments.
        current_station: Station where turn is happening.
        previous_station: Station machine came from, if any.

    Returns:
        List of stations that can be faced after turning.
    """
    _, adjacent_stations = _get_adjacent(segments, current_station)
    if not (current_station.can_turn and len(adjacent_stations) > 1):
        return []

    turn_choices: List[Station] = []
    if previous_station is not None and previous_station in adjacent_stations:
        turn_choices.append(previous_station)
    for st in adjacent_stations:
        if st in turn_choices:
            continue
        turn_choices.append(st)
        if len(turn_choices) >= 2:
            break
    if not turn_choices:
        turn_choices = adjacent_stations[:2]
    return turn_choices


def _resolve_network(config_or_path: Optional[Union[NetworkConfig, str, Path]] = None) -> NetworkConfig:
    """Resolve a network config from various input types.

    Args:
        config_or_path: NetworkConfig object, path string, Path object, or None for default.

    Returns:
        Resolved NetworkConfig instance.
    """
    if isinstance(config_or_path, NetworkConfig):
        return config_or_path
    if config_or_path is None:
        return _DEFAULT_CONFIG
    return load_network(Path(config_or_path))


def build_network(config_or_path: Optional[Union[NetworkConfig, str, Path]] = None) -> Tuple[Dict[str, Station], List[Segment]]:
    """Create and return a railroad network defined in JSON.

    Args:
        config_or_path: NetworkConfig object, path to JSON file, or None for default network.

    Returns:
        Tuple of (stations_dict, segments_list) representing the network.
    """
    config = _resolve_network(config_or_path)
    return config.stations, config.segments


__all__ = [
    "_get_adjacent",
    "_get_possible_moves",
    "_get_turn_choices",
    "_resolve_network",
    "build_network",
]
