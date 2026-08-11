"""Tests for the Auto Planner rolling-horizon travel-time graph helper."""
from src.models import Segment, Station
from railroad_backend.services.auto_planner_strategies.travel_graph import (
    build_travel_graph,
    shortest_travel_days,
)


def _linear_segments():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=2)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=3)
    return [seg_ab, seg_bc]


def test_shortest_travel_days_single_hop():
    graph = build_travel_graph(_linear_segments())
    assert shortest_travel_days(graph, "A", "B") == 2


def test_shortest_travel_days_multi_hop_sums_weights():
    graph = build_travel_graph(_linear_segments())
    assert shortest_travel_days(graph, "A", "C") == 5


def test_shortest_travel_days_unreachable_returns_none():
    graph = build_travel_graph(_linear_segments())
    graph.add_node("Z")
    assert shortest_travel_days(graph, "A", "Z") is None
