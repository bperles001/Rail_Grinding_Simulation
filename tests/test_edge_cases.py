"""Additional tests for improved coverage of edge cases and error conditions."""
import json
from pathlib import Path

import pandas as pd
import pytest

from railroad_backend.services.auto_planner import AutoPlanConfig, _days_until_next_threshold, _needs_maintenance
from railroad_backend.services.manual_planner import ManualPlanConfig, list_available_moves, replay_manual_plan
from src.models import Segment, Station
from src.simulator import Simulator


def test_auto_plan_config_validation_catches_invalid_csv_path(tmp_path):
    """AutoPlanConfig validation rejects nonexistent CSV files."""
    missing_csv = tmp_path / "missing.csv"
    with pytest.raises(ValueError, match="not found"):
        AutoPlanConfig(
            csv_path=missing_csv,
            start_station="TRO",
            facing_station="TMI",
            start_year=2020,
            end_year=2025,
            second_kld=False,
        )


def test_auto_plan_config_validation_rejects_empty_station_names(tmp_path):
    """AutoPlanConfig validation rejects empty station names."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    with pytest.raises(ValueError, match="cannot be empty"):
        AutoPlanConfig(
            csv_path=csv_path,
            start_station="",
            facing_station="TMI",
            start_year=2020,
            end_year=2025,
            second_kld=False,
        )


def test_auto_plan_config_validation_rejects_invalid_year_range(tmp_path):
    """AutoPlanConfig validation rejects end_year before start_year."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    with pytest.raises(ValueError, match="cannot be before"):
        AutoPlanConfig(
            csv_path=csv_path,
            start_station="TRO",
            facing_station="TMI",
            start_year=2025,
            end_year=2020,
            second_kld=False,
        )


def test_auto_plan_config_validation_rejects_negative_steps(tmp_path):
    """AutoPlanConfig validation rejects negative steps."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    with pytest.raises(ValueError, match="non-negative"):
        AutoPlanConfig(
            csv_path=csv_path,
            start_station="TRO",
            facing_station="TMI",
            start_year=2020,
            end_year=2025,
            second_kld=False,
            steps=-10,
        )


def test_manual_plan_config_validation_similar_to_auto(tmp_path):
    """ManualPlanConfig has similar validation to AutoPlanConfig."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    with pytest.raises(ValueError, match="cannot be empty"):
        ManualPlanConfig(
            csv_path=csv_path,
            start_station="",
            facing_station="TMI",
            start_year=2020,
            end_year=2025,
            second_kld=False,
        )


def test_simulator_wait_days_validates_input():
    """Simulator.wait_days validates days parameter."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    
    # Should reject non-integer
    with pytest.raises(TypeError, match="must be int"):
        sim.wait_days("5")  # type: ignore[arg-type]
    
    # Should reject negative
    with pytest.raises(ValueError, match="at least 1"):
        sim.wait_days(0)


def test_simulator_move_to_validates_inputs():
    """Simulator.move_to validates segment, station, and action."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    
    segment = sim.segments[0]
    station = sim.stations["TMI"]
    
    # Should reject invalid action code
    with pytest.raises(ValueError, match="action must be"):
        sim.move_to(segment, station, action="invalid")
    
    # Should reject non-Segment
    with pytest.raises(TypeError, match="seg must be Segment"):
        sim.move_to("not_a_segment", station, action="v")  # type: ignore[arg-type]
    
    # Should reject non-Station
    with pytest.raises(TypeError, match="next_station must be Station"):
        sim.move_to(segment, "not_a_station", action="v")  # type: ignore[arg-type]


def test_simulator_init_machine_validates_inputs():
    """Simulator.init_machine validates all inputs."""
    sim = Simulator()
    
    # Invalid year (below 1900)
    with pytest.raises(ValueError, match="between 1900"):
        sim.init_machine("TRO", "TMI", start_year=1800)
    
    # Invalid year (above 2200)
    with pytest.raises(ValueError, match="between 1900"):
        sim.init_machine("TRO", "TMI", start_year=2300)
    
    # Wrong type for second_kld
    with pytest.raises(TypeError, match="second_kld_installed must be bool"):
        sim.init_machine("TRO", "TMI", start_year=2025, second_kld_installed="yes")  # type: ignore[arg-type]


def test_needs_maintenance_handles_missing_threshold():
    """_needs_maintenance correctly handles segments without mtbt_threshold."""
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, 10, 0.0, 1, 1)
    seg.mtbt_threshold = None  # type: ignore[assignment]
    seg.load = 1000  # Lots of load but no threshold
    
    result = _needs_maintenance(seg)
    assert result is False  # No threshold means no maintenance needed


def test_needs_maintenance_handles_edge_case_exactly_at_threshold():
    """_needs_maintenance returns True when load exactly equals threshold."""
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, 10, 5.0, 1, 1)
    seg.load = 5.0  # Exactly at threshold
    
    result = _needs_maintenance(seg)
    assert result is True


def test_days_until_next_threshold_returns_zero_when_no_daily_map():
    """_days_until_next_threshold returns 0 when simulator has no daily_map."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    sim.daily_map = None
    
    result = _days_until_next_threshold(sim)
    assert result == 0


def test_days_until_next_threshold_returns_zero_when_already_due():
    """_days_until_next_threshold returns 0 when segments already need maintenance."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025, daily_map={})
    
    # Make a segment need maintenance
    seg = sim.segments[0]
    if seg.mtbt_threshold:
        seg.load = seg.mtbt_threshold + 1
    
    result = _days_until_next_threshold(sim)
    assert result == 0


def test_list_available_moves_returns_empty_when_no_machine():
    """list_available_moves returns empty list when machine not initialized."""
    sim = Simulator()
    # Don't initialize machine
    moves = list_available_moves(sim)
    assert moves == []


def test_replay_manual_plan_validates_plan_structure(tmp_path):
    """replay_manual_plan validates plan structure before execution."""
    # Create minimal CSV for config
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    
    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    # Invalid plan with wrong mode
    invalid_plan = [{"mode": "invalid_mode"}]
    result = replay_manual_plan(config, invalid_plan)
    
    # Should have validation errors
    assert len(result.errors) > 0
    assert any("mode must be" in err for err in result.errors)


def test_replay_manual_plan_handles_empty_plan(tmp_path):
    """replay_manual_plan handles empty plan without errors."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,1.0\n")
    
    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    result = replay_manual_plan(config, [])
    assert result.errors == []
    assert result.simulator is not None


def test_simulator_handles_segment_with_zero_threshold():
    """Simulator correctly handles segments with mtbt_threshold of 0."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    
    # Find or create segment with zero threshold
    seg = sim.segments[0]
    seg.mtbt_threshold = 0
    seg.load = 100  # Lots of load
    
    # Segment with zero threshold DOES trigger maintenance (100 >= 0 is True)
    # This is the current behavior - treating 0 as "always needs maintenance"
    assert _needs_maintenance(seg) is True


def test_simulator_flip_global_direction_at_non_turn_station():
    """Simulator.flip_global_direction returns False at non-turn stations."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    
    # Move to a non-turn station if possible
    # TMI typically doesn't allow turns
    seg = next((s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI"), None)
    if seg:
        sim.move_to(seg, seg.end_station, action="v")
        # At TMI now, which doesn't allow turns
        if not sim.current_station.can_turn:
            result = sim.flip_global_direction()
            assert result is False


def test_segment_load_operations():
    """Test segment load addition and reset operations."""
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, 10, 0.0, 1, 1)
    seg.mtbt_threshold = 10.0
    
    # add_load should accumulate
    seg.add_load(3.0)
    assert seg.load == pytest.approx(3.0)
    seg.add_load(2.5)
    assert seg.load == pytest.approx(5.5)
    
    # add_mtbt is alias for add_load
    seg.add_mtbt(1.5)
    assert seg.load == pytest.approx(7.0)
    # reset_maintenance should zero load and clear flag
    seg.load = 12.0  # Over threshold
    assert seg.maintenance_due  # Check truthiness instead of exact True
    seg.reset_maintenance()
    assert seg.load == 0.0
    assert not seg.maintenance_due
    assert seg.maintenance_due is False


def test_station_segments_registration():
    """Test that segments properly register with their stations."""
    sta = Station("A", can_turn=True)
    stb = Station("B")
    seg = Segment("A-B", sta, stb, 10, 5.0, 1, 1)
    
    assert seg in sta.segments
    assert seg in stb.segments
    assert sta.can_turn is True
    assert stb.can_turn is False


def test_simulator_with_invalid_network_path():
    """Simulator raises error when network file doesn't exist."""
    with pytest.raises(Exception):  # NetworkConfigError
        Simulator(network_reference="/nonexistent/path.json")
