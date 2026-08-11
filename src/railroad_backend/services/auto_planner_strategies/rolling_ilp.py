"""CP-SAT solver for a single rolling-horizon planning window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Tuple

from ortools.sat.python import cp_model

from .travel_graph import shortest_travel_days

if TYPE_CHECKING:
    import networkx as nx

    from .horizon import DueCandidate

_BIG_HORIZON = 3650  # upper bound on any arrival day inside a window, in days


@dataclass(frozen=True)
class WindowStop:
    station_name: str
    segment_name: str
    arrival_day: int


@dataclass(frozen=True)
class WindowPlan:
    stops: List[WindowStop]
    feasible: bool


def solve_window(
    candidates: List["DueCandidate"],
    graph: "nx.DiGraph",
    start_station: str,
    *,
    weight_coverage: float,
    weight_travel: float,
    weight_proximity: float,
    time_limit_s: float = 20.0,
) -> WindowPlan:
    if not candidates:
        return WindowPlan(stops=[], feasible=True)

    # Node 0 is the depot (current position). Nodes 1..n are candidates.
    # Only keep candidates actually reachable from the depot within the graph.
    reachable: List[Tuple[int, "DueCandidate", int]] = []
    for idx, candidate in enumerate(candidates, start=1):
        travel_days = shortest_travel_days(graph, start_station, candidate.station_name)
        if travel_days is not None:
            reachable.append((idx, candidate, travel_days))
    if not reachable:
        return WindowPlan(stops=[], feasible=True)

    nodes = [0] + [idx for idx, _, _ in reachable]
    by_node: Dict[int, "DueCandidate"] = {idx: candidate for idx, candidate, _ in reachable}
    station_by_node: Dict[int, str] = {0: start_station}
    station_by_node.update({idx: candidate.station_name for idx, candidate, _ in reachable})

    model = cp_model.CpModel()
    arcs: List[Tuple[int, int, "cp_model.IntVar"]] = []
    skip_literal: Dict[int, "cp_model.IntVar"] = {}
    arc_literal: Dict[Tuple[int, int], "cp_model.IntVar"] = {}
    arc_travel_days: Dict[Tuple[int, int], int] = {}

    for i in nodes:
        for j in nodes:
            if i == j:
                if i != 0:
                    lit = model.NewBoolVar(f"skip_{i}")
                    skip_literal[i] = lit
                    arcs.append((i, i, lit))
                continue
            travel = shortest_travel_days(graph, station_by_node[i], station_by_node[j])
            if travel is None:
                continue
            lit = model.NewBoolVar(f"arc_{i}_{j}")
            arc_literal[(i, j)] = lit
            arc_travel_days[(i, j)] = travel
            arcs.append((i, j, lit))

    model.AddCircuit(arcs)

    arrival_day: Dict[int, "cp_model.IntVar"] = {
        node: model.NewIntVar(0, _BIG_HORIZON, f"arrival_{node}") for node in nodes
    }
    model.Add(arrival_day[0] == 0)

    earliness_terms = []
    lateness_terms = []
    for (i, j), lit in arc_literal.items():
        if j == 0:
            # Fictitious return-to-depot arc, only present to let AddCircuit
            # close an otherwise-open path. It carries no real travel time
            # and must not constrain arrival_day[0] (fixed at 0, "now").
            continue
        travel = arc_travel_days[(i, j)]
        model.Add(arrival_day[j] >= arrival_day[i] + travel).OnlyEnforceIf(lit)
        due_day = by_node[j].days_until_due
        earliness = model.NewIntVar(0, _BIG_HORIZON, f"earliness_{j}")
        model.Add(earliness >= due_day - arrival_day[j]).OnlyEnforceIf(lit)
        model.Add(earliness >= 0)
        earliness_terms.append(earliness)
        # Lateness: for an already-due candidate (due_day == 0, the common
        # case), earliness alone is always satisfiable at 0 regardless of
        # when it's visited — it carries no urgency signal once a segment
        # has crossed its MTBT threshold. Without this term the solver
        # minimizes pure travel distance and happily defers already-overdue
        # segments indefinitely (confirmed on the real network: segments at
        # ~8x their threshold left unvisited while the machine looped
        # between two cheap nearby stations — 2026-08-11 diagnostic).
        lateness = model.NewIntVar(0, _BIG_HORIZON, f"lateness_{j}")
        model.Add(lateness >= arrival_day[j] - due_day).OnlyEnforceIf(lit)
        model.Add(lateness >= 0)
        lateness_terms.append(lateness)

    coverage_term = sum(skip_literal.values())
    travel_term = sum(
        arc_travel_days[(i, j)] * lit for (i, j), lit in arc_literal.items() if j != 0
    )
    proximity_term = sum(earliness_terms) if earliness_terms else 0
    lateness_term = sum(lateness_terms) if lateness_terms else 0

    # A candidate left unvisited for the rest of the window (skip) is
    # mathematically equivalent to "visited with infinite lateness" — nothing
    # in the model forces every candidate to be reached, so skip is always an
    # option the solver could pick. It must never be cheaper than the worst
    # lateness achievable by actually visiting: bound it above the largest
    # due_day plus the longest possible tour (all nodes, each hop at the most
    # expensive edge in the graph), so skipping a reachable candidate is
    # never the minimizing choice.
    max_edge_weight = max(arc_travel_days.values()) if arc_travel_days else 1
    worst_case_tour_length = len(nodes) * max_edge_weight
    max_due_day = max((c.days_until_due for c in candidates), default=0)
    skip_penalty_bound = max(1, max_due_day + worst_case_tour_length)

    scale = 1000  # CP-SAT objective coefficients must be integers
    model.Minimize(
        int(weight_coverage * scale * skip_penalty_bound) * coverage_term
        + int(weight_coverage * scale) * lateness_term
        + int(weight_travel * scale) * travel_term
        + int(weight_proximity * scale) * proximity_term
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return WindowPlan(stops=[], feasible=False)

    # Walk the circuit starting at the depot to recover visit order.
    successor: Dict[int, int] = {}
    for (i, j), lit in arc_literal.items():
        if solver.Value(lit):
            successor[i] = j
    stops: List[WindowStop] = []
    current = 0
    visited_nodes = set()
    while current in successor and successor[current] != 0:
        nxt = successor[current]
        if nxt in visited_nodes:  # pragma: no cover - defensive, circuit shouldn't loop early
            break
        visited_nodes.add(nxt)
        candidate = by_node[nxt]
        stops.append(
            WindowStop(
                station_name=station_by_node[nxt],
                segment_name=candidate.segment_name,
                arrival_day=solver.Value(arrival_day[nxt]),
            )
        )
        current = nxt

    return WindowPlan(stops=stops, feasible=True)


__all__ = ["WindowStop", "WindowPlan", "solve_window"]
