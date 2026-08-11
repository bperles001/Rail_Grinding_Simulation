"""Simulated Annealing solver for a single rolling-horizon planning window.

Same objective as the CP-SAT solver (rolling_ilp.py): minimize a weighted
sum of lateness (visiting an already-due candidate late), earliness
(visiting well before it's due -- wasted MTBT life), and total travel. Same
`WindowPlan` return type, so it plugs into `CommittedWindowStrategy`
unchanged. Search parameters (iterations/temperature/cooling) are internal
to this module -- never exposed through any UI or persisted config.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .rolling_ilp import WindowPlan, WindowStop
from .travel_graph import shortest_travel_days

if TYPE_CHECKING:
    import networkx as nx

    from .horizon import DueCandidate


def _evaluate_tour(
    order: List[str],
    candidates_by_name: Dict[str, "DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
) -> Tuple[float, List[WindowStop]]:
    day = 0
    current = start_station
    total_travel = 0
    penalty = 0.0
    stops: List[WindowStop] = []
    for name in order:
        candidate = candidates_by_name[name]
        travel = shortest_travel_days(graph, current, candidate.station_name)
        if travel is None:
            return math.inf, []
        day += travel
        total_travel += travel
        lateness = max(0, day - candidate.days_until_due)
        earliness = max(0, candidate.days_until_due - day)
        penalty += weight_coverage * lateness + weight_proximity * earliness
        stops.append(WindowStop(station_name=candidate.station_name, segment_name=candidate.segment_name, arrival_day=day))
        current = candidate.station_name
    cost = weight_travel * total_travel + penalty
    return cost, stops


def _construct_initial_order(
    candidates: List["DueCandidate"], graph: "nx.DiGraph", start_station: str
) -> List[str]:
    """Nearest-due-first greedy construction, only ever stepping to a
    reachable candidate -- guarantees the initial tour is feasible."""
    remaining = {c.segment_name: c for c in candidates}
    order: List[str] = []
    current = start_station
    while remaining:
        best_name: Optional[str] = None
        best_key: Optional[Tuple[int, int]] = None
        for name, candidate in remaining.items():
            travel = shortest_travel_days(graph, current, candidate.station_name)
            if travel is None:
                continue
            key = (candidate.days_until_due, travel)
            if best_key is None or key < best_key:
                best_key = key
                best_name = name
        if best_name is None:
            break  # nothing left is reachable from here
        order.append(best_name)
        current = remaining.pop(best_name).station_name
    return order


def solve_window_sa(
    candidates: List["DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    *,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
    iterations: int = 2000,
    initial_temperature: float = 100.0,
    cooling_rate: float = 0.995,
    seed: Optional[int] = None,
) -> WindowPlan:
    if not candidates:
        return WindowPlan(stops=[], feasible=True)

    reachable = [c for c in candidates if shortest_travel_days(graph, start_station, c.station_name) is not None]
    if not reachable:
        return WindowPlan(stops=[], feasible=True)

    candidates_by_name = {c.segment_name: c for c in reachable}
    rng = random.Random(seed)

    order = _construct_initial_order(reachable, graph, start_station)
    if not order:
        return WindowPlan(stops=[], feasible=True)

    def cost_of(candidate_order: List[str]) -> Tuple[float, List[WindowStop]]:
        return _evaluate_tour(
            candidate_order, candidates_by_name, graph, start_station,
            weight_coverage, weight_travel, weight_proximity,
        )

    current_order = list(order)
    current_cost, current_stops = cost_of(current_order)
    best_cost, best_stops = current_cost, current_stops
    temperature = initial_temperature

    for _ in range(iterations):
        if len(current_order) < 2:
            break
        i, j = rng.sample(range(len(current_order)), 2)
        candidate_order = list(current_order)
        candidate_order[i], candidate_order[j] = candidate_order[j], candidate_order[i]
        candidate_cost, candidate_stops = cost_of(candidate_order)

        delta = candidate_cost - current_cost
        accept = delta < 0 or (temperature > 1e-9 and rng.random() < math.exp(-delta / temperature))
        if accept:
            current_order, current_cost = candidate_order, candidate_cost
            if current_cost < best_cost:
                best_cost, best_stops = current_cost, candidate_stops
        temperature *= cooling_rate

    return WindowPlan(stops=best_stops, feasible=True)


__all__ = ["solve_window_sa"]
