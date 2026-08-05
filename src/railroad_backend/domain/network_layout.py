"""Reusable helpers for deriving network sketch layouts."""

from __future__ import annotations

import math
from collections import deque
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

def project_geographic_coordinates(
    coordinates: Mapping[str, Tuple[float, float]]
) -> Dict[str, Tuple[float, float]]:
    """Project {name: (lat, long)} to local planar {name: (x, y)}.

    Equirectangular approximation (x = long * cos(mean_latitude), y = lat),
    adequate at a regional scale (a single rail corridor, not a global map).
    Compresses east-west distance by the mean latitude's cosine so stations
    at higher latitude don't get visually stretched east-west.
    """
    if not coordinates:
        return {}
    mean_lat_rad = math.radians(
        sum(lat for lat, _lon in coordinates.values()) / len(coordinates)
    )
    scale = math.cos(mean_lat_rad)
    return {
        name: (lon * scale, lat)
        for name, (lat, lon) in coordinates.items()
    }


def graph_diameter_endpoints(adjacency: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    """Return two station names at opposite ends of a longest shortest-path.

    Uses the standard double-BFS technique (correct for trees, a good-enough
    heuristic otherwise): BFS from any node finds one diameter endpoint;
    BFS from that endpoint finds the other. Assumes `adjacency` represents a
    connected graph rooted at one of its own keys.
    """

    def farthest_from(start: str) -> str:
        visited = {start: 0}
        queue = deque([start])
        farthest = start
        while queue:
            node = queue.popleft()
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    visited[neighbor] = visited[node] + 1
                    if visited[neighbor] > visited[farthest]:
                        farthest = neighbor
                    queue.append(neighbor)
        return farthest

    start = next(iter(adjacency))
    first_endpoint = farthest_from(start)
    second_endpoint = farthest_from(first_endpoint)
    return first_endpoint, second_endpoint


def schematic_layout_from_seed(
    adjacency: Mapping[str, Sequence[str]],
    seed_positions: Mapping[str, Tuple[float, float]],
    *,
    spacing: float = 1.0,
) -> Dict[str, Tuple[float, float]]:
    """BFS layout that keeps each edge's real direction (from `seed_positions`)
    but normalizes every edge to the same `spacing` length.

    Only stations present in `seed_positions` participate; the walk never
    crosses into a station lacking seed data, so those are simply absent
    from the result (caller merges this over an existing layout - see
    `_render_network_layout_controls` in streamlit_app.py).
    """
    seeded = set(seed_positions)
    sub_adjacency: Dict[str, List[str]] = {
        name: [n for n in neighbors if n in seeded]
        for name, neighbors in adjacency.items()
        if name in seeded
    }
    if not sub_adjacency:
        return {}

    root, _ = graph_diameter_endpoints(sub_adjacency)
    positions: Dict[str, Tuple[float, float]] = {root: (0.0, 0.0)}
    visited = {root}
    queue = deque([root])
    while queue:
        current = queue.popleft()
        cx, cy = positions[current]
        sx, sy = seed_positions[current]
        for neighbor in sub_adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            nx_seed, ny_seed = seed_positions[neighbor]
            angle = math.atan2(ny_seed - sy, nx_seed - sx)
            positions[neighbor] = (
                cx + math.cos(angle) * spacing,
                cy + math.sin(angle) * spacing,
            )
            queue.append(neighbor)
    return positions


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
