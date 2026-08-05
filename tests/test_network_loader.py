import json
from pathlib import Path

from src.utils.network_loader import NetworkConfigError, load_network


def _write_network(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_payload() -> dict:
    return {
        "name": "Test",
        "stations": [
            {"name": "A", "can_turn": True},
            {"name": "B", "can_turn": False},
        ],
        "segments": [
            {
                "name": "A-B",
                "start": "A",
                "end": "B",
                "length_km": 1,
                "mtbt_threshold": 5,
                "move_time_days": 1,
                "maintenance_time_days": 2,
            }
        ],
        "direction_model": {},
    }


def test_load_network_parses_layout_overrides(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["layout"] = {
        "mode": "table",
        "table_overrides": {"A": {"x": 1.5, "y": 2}},
        "scale": 2.5,
    }
    path = tmp_path / "network.json"
    _write_network(path, payload)
    config = load_network(path)
    assert config.layout.mode == "table"
    assert config.layout.table_overrides["A"] == {"x": 1.5, "y": 2.0}
    assert config.layout.scale == 2.5


def test_load_network_normalizes_invalid_layout_entries(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["layout"] = {
        "mode": "invalid",
        "table_overrides": {"A": {"x": "bad", "y": None}},
        "scale": "oops",
    }
    path = tmp_path / "network.json"
    _write_network(path, payload)
    config = load_network(path)
    assert config.layout.mode == "table"
    assert config.layout.table_overrides == {}
    assert config.layout.scale == 1.0


def test_load_network_defaults_curve_tangent_and_billed_days_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "network.json"
    _write_network(path, _base_payload())
    config = load_network(path)
    segment = config.segments[0]
    assert segment.curve_length_km == 0.0
    assert segment.tangent_length_km == 0.0
    assert segment.move_billed_days == 0.0
    assert segment.maintenance_billed_days == 0.0


def test_load_network_parses_curve_tangent_and_billed_days(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["segments"][0].update(
        {
            "curve_length_km": 0.6,
            "tangent_length_km": 0.4,
            "move_billed_days": 0.5,
            "maintenance_billed_days": 1.5,
        }
    )
    path = tmp_path / "network.json"
    _write_network(path, payload)
    config = load_network(path)
    segment = config.segments[0]
    assert segment.curve_length_km == 0.6
    assert segment.tangent_length_km == 0.4
    assert segment.move_billed_days == 0.5
    assert segment.maintenance_billed_days == 1.5


def test_load_network_requires_segments_and_stations(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    _write_network(path, {"name": "bad"})
    try:
        load_network(path)
    except NetworkConfigError as exc:
        assert "stations" in str(exc)
    else:
        raise AssertionError("NetworkConfigError expected")
