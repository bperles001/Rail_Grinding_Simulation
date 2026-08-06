"""Tests for configuration validation utilities."""
from pathlib import Path

import pytest

from railroad_backend.domain.validation import (
    validate_file_path,
    validate_manual_plan,
    validate_manual_plan_step,
    validate_network_payload,
    validate_station_name,
    validate_year_range,
)


def test_validate_year_range_accepts_valid_range():
    """Year range validation accepts valid years."""
    validate_year_range(2020, 2025)  # Should not raise


def test_validate_year_range_rejects_reversed_years():
    """Year range validation rejects end before start."""
    with pytest.raises(ValueError, match="cannot be before"):
        validate_year_range(2025, 2020)


def test_validate_year_range_rejects_out_of_bounds():
    """Year range validation rejects years outside 1900-2200."""
    with pytest.raises(ValueError, match="between 1900 and 2200"):
        validate_year_range(1800, 2025)
    with pytest.raises(ValueError, match="between 1900 and 2200"):
        validate_year_range(2020, 2300)


def test_validate_year_range_rejects_non_integers():
    """Year range validation requires integer types."""
    with pytest.raises(TypeError):
        validate_year_range("2020", 2025)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_year_range(2020, 2025.0)  # type: ignore[arg-type]


def test_validate_station_name_accepts_valid_names():
    """Station name validation accepts non-empty strings."""
    validate_station_name("TRO", "start_station")
    validate_station_name("  TMI  ", "facing_station")  # Should not raise


def test_validate_station_name_rejects_empty():
    """Station name validation rejects empty or whitespace."""
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_station_name("", "start_station")
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_station_name("   ", "start_station")


def test_validate_station_name_rejects_non_string():
    """Station name validation requires string type."""
    with pytest.raises(TypeError):
        validate_station_name(123, "start_station")  # type: ignore[arg-type]


def test_validate_file_path_accepts_existing_file(tmp_path):
    """File path validation accepts existing files."""
    test_file = tmp_path / "test.csv"
    test_file.write_text("data")
    validate_file_path(test_file, must_exist=True)  # Should not raise


def test_validate_file_path_rejects_nonexistent(tmp_path):
    """File path validation rejects missing files when must_exist=True."""
    missing = tmp_path / "missing.csv"
    with pytest.raises(ValueError, match="not found"):
        validate_file_path(missing, must_exist=True)


def test_validate_file_path_accepts_nonexistent_when_optional(tmp_path):
    """File path validation allows missing files when must_exist=False."""
    missing = tmp_path / "missing.csv"
    validate_file_path(missing, must_exist=False)  # Should not raise


def test_validate_manual_plan_step_accepts_valid_move():
    """Plan step validation accepts valid move step."""
    step = {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "v"}
    errors = validate_manual_plan_step(step, 1)
    assert errors == []


def test_validate_manual_plan_step_accepts_valid_wait():
    """Plan step validation accepts valid wait step."""
    step = {"mode": "wait", "days": 5}
    errors = validate_manual_plan_step(step, 1)
    assert errors == []


def test_validate_manual_plan_step_accepts_valid_turn():
    """Plan step validation accepts valid turn step."""
    step = {"mode": "turn"}
    errors = validate_manual_plan_step(step, 1)
    assert errors == []


def test_validate_manual_plan_step_rejects_invalid_mode():
    """Plan step validation rejects invalid mode."""
    step = {"mode": "invalid"}
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "mode must be" in errors[0]


def test_validate_manual_plan_step_rejects_move_missing_fields():
    """Plan step validation rejects move step missing required fields."""
    step = {"mode": "move", "segment": "TRO-TMI"}  # Missing destination and action
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) >= 2
    assert any("destination" in e for e in errors)
    assert any("action" in e for e in errors)


def test_validate_manual_plan_step_rejects_wait_with_negative_days():
    """Plan step validation rejects wait with negative days."""
    step = {"mode": "wait", "days": -1}
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "at least 1" in errors[0]


def test_validate_manual_plan_step_rejects_invalid_action():
    """Plan step validation rejects invalid action code."""
    step = {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "x"}
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "action" in errors[0] and "'x'" in errors[0]


def test_validate_manual_plan_accepts_valid_plan():
    """Manual plan validation accepts valid multi-step plan."""
    plan = [
        {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "m"},
        {"mode": "wait", "days": 3},
        {"mode": "turn"},
    ]
    errors = validate_manual_plan(plan)
    assert errors == []


def test_validate_manual_plan_rejects_non_list():
    """Manual plan validation rejects non-list input."""
    errors = validate_manual_plan({"mode": "move"})  # type: ignore[arg-type]
    assert len(errors) == 1
    assert "must be a list" in errors[0]


def test_validate_manual_plan_collects_multiple_errors():
    """Manual plan validation collects errors from multiple steps."""
    plan = [
        {"mode": "invalid_mode"},
        {"mode": "wait", "days": -5},
        {"mode": "move"},  # Missing required fields
    ]
    errors = validate_manual_plan(plan)
    assert len(errors) >= 3  # At least one error per invalid step


def test_validate_network_payload_accepts_valid_payload():
    """Network payload validation accepts valid structure."""
    payload = {
        "name": "Test Network",
        "stations": [{"name": "TRO"}, {"name": "TMI"}],
        "segments": [
            {
                "name": "TRO-TMI",
                "start": "TRO",
                "end": "TMI",
                "length_km": 10,
                "mtbt_threshold_curva": 100,
                "mtbt_threshold_tangente": 100,
                "move_time_days": 1,
                "maintenance_time_days": 2,
            }
        ],
    }
    errors = validate_network_payload(payload)
    assert errors == []


def test_validate_network_payload_rejects_missing_stations():
    """Network payload validation rejects missing stations key."""
    payload = {"segments": []}
    errors = validate_network_payload(payload)
    assert len(errors) == 1
    assert "stations" in errors[0]


def test_validate_network_payload_rejects_missing_segments():
    """Network payload validation rejects missing segments key."""
    payload = {"stations": []}
    errors = validate_network_payload(payload)
    assert len(errors) == 1
    assert "segments" in errors[0]


def test_validate_network_payload_rejects_invalid_station_structure():
    """Network payload validation rejects invalid station entries."""
    payload = {
        "stations": [{"name": "TRO"}, "invalid", {"missing_name": "value"}],
        "segments": [],
    }
    errors = validate_network_payload(payload)
    assert len(errors) >= 2  # Invalid type + missing name field


def test_validate_network_payload_rejects_segment_missing_fields():
    """Network payload validation rejects segments missing required fields."""
    payload = {
        "stations": [{"name": "TRO"}],
        "segments": [{"name": "SEG1", "start": "TRO"}],  # Missing many fields
    }
    errors = validate_network_payload(payload)
    assert len(errors) >= 1
    assert "missing required fields" in errors[0]
