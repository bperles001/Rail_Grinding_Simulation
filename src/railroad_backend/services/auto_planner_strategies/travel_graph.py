"""Turn-aware travel-time graph for ranking candidates and for real execution.

Node = (station_name, direction), direction in {"CARREGADO", "VAZIO"} --
mirrors `Simulator.machine.global_direction`. Built by reusing the exact
functions the real Simulator uses to decide what's a legal move
(`_get_possible_moves`, `_classify_directional_segment`) -- never a parallel
reimplementation, which is what let this graph drift out of sync with real
execution in the first place (2026-08-11/12 diagnostic: the machine got
stuck oscillating between two stations because the old direction-blind
graph reported a target "reachable" that actually required a turn neither
the graph nor the execution logic knew about).

Two distance functions for two different consumers:
  - `shortest_travel_days`: the caller already knows its current
    (station, direction) -- used by real execution, where exactness matters.
  - `shortest_travel_days_any_direction`: no known direction -- used inside
    the CP-SAT/SA models to rank candidates against each other, where
    tracking direction as a tour-wide decision variable is out of scope for
    this round. Documented approximation: minimum over the 4 combinations
    of start/end direction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

import networkx as nx

from src.simulator.core import _classify_directional_segment
from src.simulator.network_utils import _get_possible_moves

if TYPE_CHECKING:
    from src.models import Segment, Station

DIRECTIONS: Tuple[str, str] = ("CARREGADO", "VAZIO")
State = Tuple[str, str]


@dataclass(frozen=True)
class PathStep:
    kind: str  # "turn" or "move"
    next_station: Optional[str]  # station name for "move"; None for "turn"


def build_travel_graph(segments: Sequence["Segment"], stations: Dict[str, "Station"]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for station in stations.values():
        for seg_tuple, other_station in _get_possible_moves(list(segments), station):
            weight = max(1, sum(int(s.move_time_days) for s in seg_tuple))
            direction = _classify_directional_segment(seg_tuple[-1], station.name)
            if direction is None:
                for d in DIRECTIONS:
                    graph.add_edge((station.name, d), (other_station.name, d), days=weight, kind="move")
            else:
                graph.add_edge((station.name, direction), (other_station.name, direction), days=weight, kind="move")
        if station.can_turn:
            carregado, vazio = (station.name, "CARREGADO"), (station.name, "VAZIO")
            graph.add_edge(carregado, vazio, days=1, kind="turn")
            graph.add_edge(vazio, carregado, days=1, kind="turn")
    return graph


def shortest_travel_days(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[int]:
    from_station, _ = from_state
    if from_station == to_station:
        return 0
    if from_state not in graph:
        return None
    best: Optional[int] = None
    for direction in DIRECTIONS:
        to_state = (to_station, direction)
        if to_state not in graph:
            continue
        try:
            length = nx.shortest_path_length(graph, from_state, to_state, weight="days")
        except nx.NetworkXNoPath:
            continue
        if best is None or length < best:
            best = length
    return best


def shortest_travel_days_any_direction(graph: nx.DiGraph, from_station: str, to_station: str) -> Optional[int]:
    if from_station == to_station:
        return 0
    best: Optional[int] = None
    for direction in DIRECTIONS:
        distance = shortest_travel_days(graph, (from_station, direction), to_station)
        if distance is None:
            continue
        if best is None or distance < best:
            best = distance
    return best


def shortest_path_first_step(graph: nx.DiGraph, from_state: State, to_station: str) -> Optional[PathStep]:
    from_station, _ = from_state
    if from_station == to_station:
        return None
    if from_state not in graph:
        return None
    best_length: Optional[int] = None
    best_path: Optional[list] = None
    for direction in DIRECTIONS:
        to_state = (to_station, direction)
        if to_state not in graph:
            continue
        try:
            length, path = nx.single_source_dijkstra(graph, from_state, to_state, weight="days")
        except nx.NetworkXNoPath:
            continue
        if best_length is None or length < best_length:
            best_length, best_path = length, path
    if not best_path or len(best_path) < 2:
        return None
    first_state, second_state = best_path[0], best_path[1]
    edge_data = graph.get_edge_data(first_state, second_state)
    if edge_data.get("kind") == "turn":
        return PathStep(kind="turn", next_station=None)
    return PathStep(kind="move", next_station=second_state[0])


__all__ = [
    "DIRECTIONS",
    "PathStep",
    "State",
    "build_travel_graph",
    "shortest_travel_days",
    "shortest_travel_days_any_direction",
    "shortest_path_first_step",
]
