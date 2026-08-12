"""Tests for the turn-aware Auto Planner travel-time state graph."""
from railroad_backend.services.auto_planner_strategies.travel_graph import (
    PathStep,
    build_travel_graph,
    shortest_path_first_step,
    shortest_travel_days,
    shortest_travel_days_any_direction,
)
from src.models import Segment, Station


def _linear_stations_and_segments():
    a, b, c = Station(name="A"), Station(name="B"), Station(name="C")
    seg_ab = Segment(name="A-B", start_station=a, end_station=b, move_time_days=2)
    seg_bc = Segment(name="B-C", start_station=b, end_station=c, move_time_days=3)
    stations = {"A": a, "B": b, "C": c}
    return stations, [seg_ab, seg_bc]


def test_shortest_travel_days_single_hop_from_known_direction():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    # A plain (unsuffixed) Singela segment is still direction-encoded:
    # departing from its start station classifies as CARREGADO (loaded/
    # outbound), matching _classify_directional_segment's real rule.
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "B") == 2


def test_shortest_travel_days_multi_hop_sums_weights():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "C") == 5


def test_directional_segment_only_reachable_in_its_own_direction():
    a, b = Station(name="A"), Station(name="B")
    # -LP suffix is always CARREGADO-only (see _classify_directional_segment).
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "B") == 1
    assert shortest_travel_days(graph, ("A", "VAZIO"), "B") is None


def test_turn_edge_costs_one_day_and_only_exists_at_can_turn_stations():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert graph.has_edge(("A", "CARREGADO"), ("A", "VAZIO"))
    assert graph.get_edge_data(("A", "CARREGADO"), ("A", "VAZIO"))["days"] == 1
    assert not graph.has_edge(("B", "CARREGADO"), ("B", "VAZIO"))


def test_reaching_a_direction_locked_segment_requires_a_turn_first():
    """A-B is CARREGADO-only. Starting at A in VAZIO, the only way to reach
    B is: turn at A (1 day) then take A-B (1 day) = 2 days total."""
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    assert shortest_travel_days(graph, ("A", "VAZIO"), "B") == 2


def test_shortest_travel_days_any_direction_takes_the_minimum():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    # From CARREGADO it's 1 day direct; from VAZIO it would need a turn (2 days).
    # The any-direction helper must report the cheaper of the two: 1.
    assert shortest_travel_days_any_direction(graph, "A", "B") == 1


def test_shortest_path_first_step_is_a_turn_when_a_turn_is_needed():
    a = Station(name="A", can_turn=True)
    b = Station(name="B", can_turn=False)
    seg = Segment(name="A-B-LP", start_station=a, end_station=b, move_time_days=1)
    stations = {"A": a, "B": b}
    graph = build_travel_graph([seg], stations)
    step = shortest_path_first_step(graph, ("A", "VAZIO"), "B")
    assert step == PathStep(kind="turn", next_station=None)


def test_shortest_path_first_step_is_a_move_when_no_turn_is_needed():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    step = shortest_path_first_step(graph, ("A", "CARREGADO"), "C")
    assert step == PathStep(kind="move", next_station="B")


def test_shortest_path_first_step_none_when_already_there():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_path_first_step(graph, ("A", "CARREGADO"), "A") is None


def test_shortest_travel_days_unreachable_returns_none():
    stations, segments = _linear_stations_and_segments()
    graph = build_travel_graph(segments, stations)
    assert shortest_travel_days(graph, ("A", "CARREGADO"), "Nowhere") is None
