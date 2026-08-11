"""Tests for the CP-SAT rolling-horizon window solver."""
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.rolling_ilp import solve_window
from railroad_backend.services.auto_planner_strategies.travel_graph import build_travel_graph
from src.models import Segment, Station


def _three_node_graph():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=1, maintenance_time_days=1)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=1, maintenance_time_days=1)
    return build_travel_graph([seg_ab, seg_bc])


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
    visited_segments = [stop.segment_name for stop in plan.stops]
    assert visited_segments == ["A-B", "B-C"]


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
