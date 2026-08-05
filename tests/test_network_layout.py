import math
from types import SimpleNamespace

from railroad_backend.domain.network_layout import (
    build_adjacency_map,
    default_station_layout,
    graph_diameter_endpoints,
    project_geographic_coordinates,
    schematic_layout_from_seed,
)
from src.models import Segment, Station


def _linear_config():
    station_a = Station("A", can_turn=True)
    station_b = Station("B")
    station_c = Station("C")
    seg_ab = Segment(name="A-B", start_station=station_a, end_station=station_b, length=1.0)
    seg_bc = Segment(name="B-C", start_station=station_b, end_station=station_c, length=1.0)
    stations = {s.name: s for s in (station_a, station_b, station_c)}
    return SimpleNamespace(stations=stations, segments=[seg_ab, seg_bc])


def test_build_adjacency_map_linear_network():
    config = _linear_config()
    adjacency = build_adjacency_map(config.segments)
    assert adjacency["A"] == ["B"]
    assert adjacency["B"] == ["A", "C"]
    assert adjacency["C"] == ["B"]


def test_default_station_layout_returns_coordinates_for_all_nodes():
    config = _linear_config()
    layout = default_station_layout(config)
    assert set(layout.keys()) == set(config.stations.keys())
    assert layout["A"]["x"] < layout["C"]["x"]
    assert all(isinstance(coords["y"], float) for coords in layout.values())


def test_project_geographic_coordinates_orders_east_west_and_north_south():
    coords = {
        "A": (-20.0, -50.0),  # further north (less negative lat), further west
        "B": (-21.0, -49.0),  # further south, further east
    }
    projected = project_geographic_coordinates(coords)
    assert projected["A"][1] > projected["B"][1]  # A further north -> larger y
    assert projected["A"][0] < projected["B"][0]  # A further west -> smaller x


def test_project_geographic_coordinates_empty():
    assert project_geographic_coordinates({}) == {}


def test_graph_diameter_endpoints_finds_unique_longest_path():
    # Trunk A-B-C-D-E-F (length 5) with a short branch C-G (max length 4
    # via G-C-D-E-F), so A-F is the unique longest path - no ties to worry
    # about in this test.
    adjacency = {
        "A": ["B"],
        "B": ["A", "C"],
        "C": ["B", "D", "G"],
        "D": ["C", "E"],
        "E": ["D", "F"],
        "F": ["E"],
        "G": ["C"],
    }
    a, b = graph_diameter_endpoints(adjacency)
    assert {a, b} == {"A", "F"}


def test_graph_diameter_endpoints_on_two_node_graph():
    adjacency = {"A": ["B"], "B": ["A"]}
    a, b = graph_diameter_endpoints(adjacency)
    assert {a, b} == {"A", "B"}


def test_schematic_layout_from_seed_preserves_direction_normalizes_length():
    adjacency = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}
    # B is due east of A (same y); C is due north of B (same x as B).
    seed = {"A": (0.0, 0.0), "B": (10.0, 0.0), "C": (10.0, 10.0)}
    result = schematic_layout_from_seed(adjacency, seed, spacing=2.0)

    assert set(result) == {"A", "B", "C"}
    ax, ay = result["A"]
    bx, by = result["B"]
    cx, cy = result["C"]

    # A -> B direction preserved (east): B east of A, same y.
    assert bx > ax
    assert math.isclose(by, ay, abs_tol=1e-9)
    # B -> C direction preserved (north): C north of B, same x as B.
    assert math.isclose(cx, bx, abs_tol=1e-9)
    assert cy > by
    # Spacing normalized: both edges have length == spacing, regardless of
    # the seed's real (10-unit) distances.
    assert math.isclose(math.hypot(bx - ax, by - ay), 2.0, abs_tol=1e-9)
    assert math.isclose(math.hypot(cx - bx, cy - by), 2.0, abs_tol=1e-9)


def test_schematic_layout_from_seed_skips_stations_without_seed_data():
    adjacency = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}
    seed = {"A": (0.0, 0.0), "B": (10.0, 0.0)}  # C has no seed data
    result = schematic_layout_from_seed(adjacency, seed, spacing=1.0)
    assert set(result) == {"A", "B"}


def test_schematic_layout_from_seed_empty_seed_returns_empty():
    assert schematic_layout_from_seed({"A": ["B"]}, {}, spacing=1.0) == {}


def test_schematic_layout_from_seed_branch_point_fans_out_children():
    # B connects to A, C, and D - a branch point, like ZIQ in the real network.
    adjacency = {"A": ["B"], "B": ["A", "C", "D"], "C": ["B"], "D": ["B"]}
    seed = {
        "A": (0.0, 0.0),
        "B": (10.0, 0.0),   # east of A
        "C": (10.0, 10.0),  # north of B
        "D": (20.0, 0.0),   # east of B
    }
    result = schematic_layout_from_seed(adjacency, seed, spacing=1.0)
    assert set(result) == {"A", "B", "C", "D"}
    bx, by = result["B"]
    cx, cy = result["C"]
    dx, dy = result["D"]
    assert math.isclose(cx, bx, abs_tol=1e-9) and cy > by  # C stays north of B
    assert dx > bx and math.isclose(dy, by, abs_tol=1e-9)  # D stays east of B
