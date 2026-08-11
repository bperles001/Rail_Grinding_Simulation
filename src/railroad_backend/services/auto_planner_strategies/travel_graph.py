"""Travel-time graph for ranking candidates inside a rolling-horizon plan.

This graph is a simplification: it ignores the CARREGADO/VAZIO facing
restriction that `Simulator.get_possible_moves()` enforces at execution
time, and ignores turn-station mechanics. It is only used to rank
candidates inside `RollingHorizonILPStrategy`'s planning window — the real
next single step is always re-validated against `sim.get_possible_moves()`
before execution, so an optimistic distance estimate here cannot produce
an invalid real move.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

import networkx as nx

if TYPE_CHECKING:
    from src.models import Segment


def build_travel_graph(segments: Sequence["Segment"]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for segment in segments:
        weight = max(1, int(segment.move_time_days))
        for src, dst in segment.allowed_movements:
            graph.add_edge(src, dst, days=weight)
    return graph


def shortest_travel_days(graph: nx.DiGraph, from_station: str, to_station: str) -> Optional[int]:
    if from_station == to_station:
        return 0
    if from_station not in graph or to_station not in graph:
        return None
    try:
        return nx.shortest_path_length(graph, from_station, to_station, weight="days")
    except nx.NetworkXNoPath:
        return None


__all__ = ["build_travel_graph", "shortest_travel_days"]
