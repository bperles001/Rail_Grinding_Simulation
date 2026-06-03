import json
from pathlib import Path

from src.simulator import Simulator, _classify_edge_global_dir


def test_classify_edge_global_dir_segment_based():
    """Test that direction classification uses segment allowed_movements."""
    # Default network has TRO->TMI segment with both directions allowed
    # Start->End direction is CARREGADO
    assert _classify_edge_global_dir("TRO", "TMI") == "CARREGADO"
    # End->Start direction is VAZIO
    assert _classify_edge_global_dir("TMI", "TRO") == "VAZIO"


def test_simulator_possible_moves_respect_global_direction():
    sim = Simulator()
    sim.init_machine(start_station_name="TRO", facing_station_name="TMI", start_year=2025)
    moves = sim.get_possible_moves()
    assert moves, "Expected at least one allowable move"
    direction = sim.machine.global_direction
    for segment, station in moves:
        assert sim.classify_edge_direction(sim.current_station.name, station.name) == direction
        assert segment in sim.segments


def _write_network_with_segments(tmp_path: Path, stations: list[str], segments: list[dict]) -> Path:
    """Create a test network with explicit segment definitions.
    
    Args:
        tmp_path: Temporary directory
        stations: List of station names
        segments: List of segment dicts with 'start', 'end', 'allowed_movements'
    """
    payload = {
        "name": "custom",
        "stations": [{"name": name, "can_turn": True} for name in stations],
        "segments": [
            {
                "name": seg.get("name", f"{seg['start']}-{seg['end']}"),
                "start": seg["start"],
                "end": seg["end"],
                "length_km": seg.get("length_km", 1.0),
                "mtbt_threshold": seg.get("mtbt_threshold", 10.0),
                "move_time_days": seg.get("move_time_days", 1),
                "maintenance_time_days": seg.get("maintenance_time_days", 1),
                "allowed_movements": seg.get("allowed_movements", [[seg["start"], seg["end"]], [seg["end"], seg["start"]]]),
            }
            for seg in segments
        ],
    }
    path = tmp_path / "network.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_classify_edge_uses_segment_direction(tmp_path):
    """Test that classification uses segment Start/End to determine direction."""
    path = _write_network_with_segments(
        tmp_path,
        stations=["A", "B", "C"],
        segments=[
            {"start": "A", "end": "B"},  # Both directions allowed by default
            {"start": "B", "end": "C"},  # Both directions allowed by default
        ]
    )
    sim = Simulator(path)
    # Start->End is CARREGADO
    assert sim.classify_edge_direction("A", "B") == "CARREGADO"
    # End->Start is VAZIO
    assert sim.classify_edge_direction("B", "A") == "VAZIO"
    # Non-adjacent stations return None (no direct segment)
    assert sim.classify_edge_direction("A", "C") is None


def test_unidirectional_segment(tmp_path):
    """Test that unidirectional segments only allow one direction."""
    path = _write_network_with_segments(
        tmp_path,
        stations=["X", "Y"],
        segments=[
            {"start": "X", "end": "Y", "allowed_movements": [["X", "Y"]]},  # Only X->Y allowed
        ]
    )
    sim = Simulator(path)
    # X->Y is allowed (CARREGADO)
    assert sim.classify_edge_direction("X", "Y") == "CARREGADO"
    # Y->X is NOT allowed (no movement defined)
    assert sim.classify_edge_direction("Y", "X") is None


def test_bidirectional_segments(tmp_path):
    """Test that segments with both directions classify correctly."""
    path = _write_network_with_segments(
        tmp_path,
        stations=["A", "B", "X"],
        segments=[
            {"start": "A", "end": "B"},  # Bidirectional main line
            {"start": "A", "end": "X"},  # Bidirectional spur
        ]
    )
    sim = Simulator(path)
    # Main line directions
    assert sim.classify_edge_direction("A", "B") == "CARREGADO"
    assert sim.classify_edge_direction("B", "A") == "VAZIO"
    # Spur directions
    assert sim.classify_edge_direction("A", "X") == "CARREGADO"
    assert sim.classify_edge_direction("X", "A") == "VAZIO"
