from types import SimpleNamespace

from railroad_backend.domain.network_layout import build_adjacency_map, default_station_layout
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
