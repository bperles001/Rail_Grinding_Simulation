"""Tests for the Simulated Annealing rolling-horizon window solver."""
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.simulated_annealing import solve_window_sa
from railroad_backend.services.auto_planner_strategies.travel_graph import build_travel_graph
from src.models import Segment, Station


def test_solve_window_sa_empty_candidates_returns_feasible_empty_plan():
    a = Station(name="A")
    seg = Segment(name="A-A", start_station=a, end_station=a, move_time_days=1, maintenance_time_days=1)
    graph = build_travel_graph([seg])
    plan = solve_window_sa([], graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1)
    assert plan.feasible
    assert plan.stops == []


def test_solve_window_sa_skips_unreachable_candidate_instead_of_failing():
    a, b = Station(name="A"), Station(name="B")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    graph = build_travel_graph([seg_ab])
    candidates = [
        DueCandidate(segment_name="A-B", station_name="B", days_until_due=5, service_days=1),
        DueCandidate(segment_name="ghost", station_name="Nowhere", days_until_due=1, service_days=1),
    ]
    plan = solve_window_sa(candidates, graph, start_station="A", weight_coverage=1.0, weight_travel=1.0, weight_proximity=0.1, seed=42)
    assert plan.feasible
    visited = [stop.segment_name for stop in plan.stops]
    assert "A-B" in visited
    assert "ghost" not in visited


def test_solve_window_sa_prioritizes_already_due_candidate_over_cheaper_route():
    """Mirrors the CP-SAT regression test (test_rolling_ilp.py) with the same
    D/X/Y graph and weights: X is already due and reachable only by a more
    expensive direct route; Y is not urgent but sits on a cheaper detour that
    would delay X. X must still be visited first."""
    d, x, y = Station(name="D"), Station(name="X"), Station(name="Y")
    seg_dx = Segment(name="D-X", start_station=d, end_station=x, move_time_days=3, maintenance_time_days=1)
    seg_dy = Segment(name="D-Y", start_station=d, end_station=y, move_time_days=1, maintenance_time_days=1)
    seg_xy = Segment(name="X-Y", start_station=x, end_station=y, move_time_days=10, maintenance_time_days=1)
    graph = build_travel_graph([seg_dx, seg_dy, seg_xy])

    candidates = [
        DueCandidate(segment_name="D-X", station_name="X", days_until_due=0, service_days=1),
        DueCandidate(segment_name="D-Y", station_name="Y", days_until_due=1000, service_days=1),
    ]
    plan = solve_window_sa(
        candidates, graph, start_station="D",
        weight_coverage=100.0, weight_travel=1.0, weight_proximity=0.0,
        seed=7,
    )
    assert plan.feasible
    visited = [stop.segment_name for stop in plan.stops]
    assert visited[0] == "D-X", f"expected already-due D-X visited first, got order {visited}"
