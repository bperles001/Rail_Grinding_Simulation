"""Reusable helpers for deriving network sketch layouts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Sequence, Tuple

import networkx as nx

from src.models import Segment

if TYPE_CHECKING:
    from src.utils.network_loader import NetworkConfig


def _normalize_positions(raw_positions: Mapping[Any, Any]) -> Dict[str, Tuple[float, float]]:
    normalized: Dict[str, Tuple[float, float]] = {}
    for node, coords in raw_positions.items():
        try:
            x_val = float(coords[0])
            y_val = float(coords[1])
        except (TypeError, ValueError, IndexError):
            continue
        normalized[str(node)] = (x_val, y_val)
    return normalized


def build_adjacency_map(segments: Sequence[Segment]) -> Dict[str, List[str]]:
    """Return sorted adjacency lists for each station in the segment list."""
    adjacency: Dict[str, set[str]] = {}
    for seg in segments:
        adjacency.setdefault(seg.start_station.name, set()).add(seg.end_station.name)
        adjacency.setdefault(seg.end_station.name, set()).add(seg.start_station.name)
    return {name: sorted(neighbors) for name, neighbors in adjacency.items()}


def station_order_from_config(config: "NetworkConfig") -> List[str]:
    """Preserve the station ordering defined inside the network config."""
    return list(config.stations.keys())


def automatic_layout_positions(graph: nx.Graph) -> Dict[str, Tuple[float, float]]:
    """Produce a deterministic layout for the provided networkx graph."""
    if graph.number_of_nodes() == 1:
        node = next(iter(graph.nodes))
        return {node: (0.0, 0.0)}
    simple_graph: nx.Graph = nx.Graph()
    simple_graph.add_nodes_from(graph.nodes)
    simple_graph.add_edges_from(graph.to_undirected().edges())
    try:
        is_planar, _ = nx.check_planarity(simple_graph)
    except nx.NetworkXException:
        is_planar = False
    if is_planar and simple_graph.number_of_edges() > 0:
        planar_pos = _normalize_positions(nx.planar_layout(simple_graph, scale=1.0, center=(0.0, 0.0)))
        return {node: planar_pos.get(node, (0.0, 0.0)) for node in graph.nodes}
    try:
        kamada_pos = _normalize_positions(nx.kamada_kawai_layout(graph))
        return {node: kamada_pos.get(node, (0.0, 0.0)) for node in graph.nodes}
    except Exception:
        spring_pos = _normalize_positions(nx.spring_layout(graph, seed=42))
        return {node: spring_pos.get(node, (0.0, 0.0)) for node in graph.nodes}


def automatic_station_layout(config: "NetworkConfig") -> Dict[str, Dict[str, float]]:
    """Generate normalized station coordinates based on graph topology."""
    graph: nx.Graph = nx.Graph()
    for station in config.stations.values():
        graph.add_node(station.name)
    for segment in config.segments:
        graph.add_edge(segment.start_station.name, segment.end_station.name)
    if graph.number_of_nodes() == 0:
        return {}
    positions = automatic_layout_positions(graph)
    if not positions:
        return {}
    xs = [coords[0] for coords in positions.values()]
    ys = [coords[1] for coords in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    scale = max(len(positions), 1)
    normalized: Dict[str, Dict[str, float]] = {}
    for name, coords in positions.items():
        x_norm = ((coords[0] - min_x) / span_x) * scale
        y_norm = ((coords[1] - min_y) / span_y) * scale
        normalized[name] = {"x": float(x_norm), "y": float(y_norm)}
    return normalized

def default_station_layout(config: "NetworkConfig") -> Dict[str, Dict[str, float]]:
    """Provide deterministic fallback coordinates using adjacency heuristics."""
    auto_coords = automatic_station_layout(config)
    if auto_coords:
        return auto_coords
    order = station_order_from_config(config)
    adjacency = build_adjacency_map(config.segments)
    positions: Dict[str, Dict[str, float]] = {}
    for idx, name in enumerate(order):
        degree = len(adjacency.get(name, []))
        base_y = 0.0
        if degree >= 4:
            base_y = 1.0
        elif degree == 3:
            base_y = 0.5
        elif degree <= 1 and idx % 2:
            base_y = -0.5
        positions[name] = {"x": float(idx), "y": base_y}
    return positions
