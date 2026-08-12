"""Tests for the CP-SAT rolling-horizon window solver."""
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.rolling_ilp import solve_window
from railroad_backend.services.auto_planner_strategies.travel_graph import build_travel_graph
from src.models import Segment, Station


def _three_node_graph():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=1, maintenance_time_days=1)
    stations = {"A": a, "B": b, "C": c}
    return build_travel_graph([seg_ab, seg_bc], stations)


def test_solve_window_visits_both_reachable_candidates_when_cheap():
    graph = _three_node_graph()
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=10, service_days=1),
        DueCandidate(segment_name="B-C", station_name="C", days_until_due=20, service_days=1),
    ]
    plan = solve_window(
        candidates, graph, start_station="A",
        weight_coverage=100.0, weight_travel=1.0, weight_proximity=0.1,
        time_limit_s=5.0,
    )
    assert plan.feasible
    visited_segments = {stop.segment_name for stop in plan.stops}
    # Order isn't asserted here: with the turn-aware graph, closing the
    # AddCircuit loop back to the depot may only be physically possible via
    # one particular visiting order (e.g. this fixture's only return path
    # to A is the VAZIO leg out of B -- there's no direct return from C).
    # What this test actually cares about is that both cheap, reachable
    # candidates get visited, not which order that happens in.
    assert visited_segments == {"A-B", "B-C"}


def test_solve_window_skips_unreachable_candidate_instead_of_failing():
    graph = _three_node_graph()
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=10, service_days=1),
        DueCandidate(segment_name="ghost", station_name="Nowhere", days_until_due=5, service_days=1),
    ]
    plan = solve_window(
        candidates, graph, start_station="A",
        weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1,
        time_limit_s=5.0,
    )
    assert plan.feasible
    visited_segments = [stop.segment_name for stop in plan.stops]
    assert "A-B" in visited_segments
    assert "ghost" not in visited_segments


def test_solve_window_empty_candidates_returns_feasible_empty_plan():
    graph = _three_node_graph()
    plan = solve_window([], graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1)
    assert plan.feasible
    assert plan.stops == []


def test_solve_window_prioritizes_already_due_candidate_over_cheaper_route():
    """Regression test for the missing-lateness-penalty bug: a segment that is
    already overdue (days_until_due=0) must be visited before a much-less-urgent
    one (days_until_due=1000), even when visiting the less-urgent one first
    would minimize total travel distance. Reproduced on the real network as
    persistent oscillation between two nearby stations while segments loaded
    at ~8x their MTBT threshold sat unvisited nearby (2026-08-11 diagnostic)."""
    d, x, y = Station(name="D"), Station(name="X"), Station(name="Y")
    # D-X (3) and D-Y (1) are both direct from the depot; X-Y (10) is an
    # expensive detour, so touring "Y then X" is 2 days cheaper in raw
    # travel (11 vs 13) than "X then Y" -- but X is already due and Y is
    # not, so visiting X first should still win once lateness is priced in.
    seg_dx = Segment(name="D-X", start_station=d, end_station=x, move_time_days=3, maintenance_time_days=1)
    seg_dy = Segment(name="D-Y", start_station=d, end_station=y, move_time_days=1, maintenance_time_days=1)
    seg_xy = Segment(name="X-Y", start_station=x, end_station=y, move_time_days=10, maintenance_time_days=1)
    stations = {"D": d, "X": x, "Y": y}
    graph = build_travel_graph([seg_dx, seg_dy, seg_xy], stations)

    candidates = [
        DueCandidate(segment_name="D-X", station_name="X", days_until_due=0, service_days=1),
        DueCandidate(segment_name="D-Y", station_name="Y", days_until_due=1000, service_days=1),
    ]
    plan = solve_window(
        candidates, graph, start_station="D",
        weight_coverage=100.0, weight_travel=1.0, weight_proximity=0.0,
        time_limit_s=5.0,
    )
    assert plan.feasible
    visited_segments = [stop.segment_name for stop in plan.stops]
    assert visited_segments[0] == "D-X", (
        f"expected already-due D-X visited first despite higher travel cost, got order {visited_segments}"
    )
