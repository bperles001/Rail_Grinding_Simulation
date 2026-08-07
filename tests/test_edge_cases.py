"""Additional tests for improved coverage of edge cases and error conditions."""
import json
from pathlib import Path

import pandas as pd
import pytest

from railroad_backend.services.auto_planner import AutoPlanConfig, _days_until_next_threshold, _needs_maintenance
from railroad_backend.services.manual_planner import ManualPlanConfig, list_available_moves, replay_manual_plan
from src.models import Segment, Station
from src.simulator import Simulator


def _write_trio_network(tmp_path):
    """Two stations linked by Singela + LP (B->A) + LD (A->B), like TAG-TRO."""
    payload = {
        "name": "trio",
        "stations": [{"name": "A", "can_turn": True}, {"name": "B", "can_turn": True}],
        "segments": [
            {
                "name": "A-B", "start": "A", "end": "B", "length_km": 10.0,
                "mtbt_threshold_curva": 100.0, "mtbt_threshold_tangente": 100.0,
                "move_time_days": 2, "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            },
            {
                "name": "A-B-LD", "start": "A", "end": "B", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["A", "B"]],
            },
            {
                "name": "A-B-LP", "start": "B", "end": "A", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["B", "A"]],
            },
        ],
    }
    path = tmp_path / "trio_network.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_possible_moves_pairs_singela_with_directional_segment(tmp_path):
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    moves = sim.get_all_moves_any_direction()
    assert len(moves) == 1
    segments, destination = moves[0]
    assert destination.name == "B"
    names = {s.name for s in segments}
    assert names == {"A-B", "A-B-LD"}
    # directional segment (the one with a single allowed direction) is last
    assert len(segments[-1].allowed_movements) == 1
    assert segments[-1].name == "A-B-LD"


def test_get_possible_moves_no_singela_still_returns_single_segment():
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    moves = sim.get_all_moves_any_direction()
    assert moves, "expected at least one move on the default network"
    for segments, _station in moves:
        assert len(segments) == 1  # default.json has no Singela+LP/LD trios


def test_move_to_with_segment_tuple_applies_effects_to_both_and_sums_duration(tmp_path):
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    assert len(segments) == 2

    before = sim.simulation_date
    sim.move_to(segments, destination, action="v")
    # move_time_days: 2 (Singela) + 1 (directional) = 3
    assert (sim.simulation_date - before).days == 3
    assert sim.steps[-1]["days"] == 3
    assert sim.steps[-1]["segments"] == ["A-B", "A-B-LD"]
    assert sim.steps[-1]["segment"] == "A-B-LD"


def test_move_to_maintenance_with_segment_tuple_resets_both(tmp_path):
    from src.models import ACTION_MAINTAIN

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.mtbt_threshold_curva = 5.0
    singela.mtbt_threshold_tangente = 5.0
    singela.add_load(10.0)
    directional.add_load(10.0)
    assert singela.maintenance_due is True
    assert directional.maintenance_due is True

    sim.machine.second_kld_installed = True  # force perform_maintenance regardless of direction
    sim.move_to(segments, destination, action=ACTION_MAINTAIN)

    assert singela.load_curva == 0.0 and singela.load_tangente == 0.0
    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0
    # maintenance_time_days: 3 (Singela) + 1 (directional) = 4
    assert sim.steps[-1]["days"] == 4


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
    with pytest.raises(TypeError, match="segments must contain only Segment instances"):
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
    """_needs_maintenance correctly handles segments without a threshold set."""
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10)
    seg.mtbt_threshold_curva = None  # type: ignore[assignment]
    seg.mtbt_threshold_tangente = None  # type: ignore[assignment]
    seg.load_curva = 1000  # Lots of load but no threshold
    seg.load_tangente = 1000

    result = _needs_maintenance(seg)
    assert result is False  # No threshold means no maintenance needed


def test_needs_maintenance_true_when_only_curva_due():
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(5.0)
    assert _needs_maintenance(seg) is True


def test_needs_maintenance_false_when_neither_due():
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(1.0)
    assert _needs_maintenance(seg) is False


def test_maintenance_action_is_curves_only_when_only_curva_due():
    from railroad_backend.services.auto_planner import _maintenance_action_for
    from src.models import ACTION_MAINTAIN_CURVES

    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=100.0)
    seg.add_load(5.0)
    assert _maintenance_action_for(seg) == ACTION_MAINTAIN_CURVES


def test_maintenance_action_is_full_when_tangente_due():
    from railroad_backend.services.auto_planner import _maintenance_action_for
    from src.models import ACTION_MAINTAIN

    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=5.0)
    seg.add_load(5.0)
    assert _maintenance_action_for(seg) == ACTION_MAINTAIN


def test_needs_maintenance_handles_edge_case_exactly_at_threshold():
    """_needs_maintenance returns True when load exactly equals threshold."""
    start = Station("A")
    end = Station("B")
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=5.0, mtbt_threshold_tangente=5.0)
    seg.load_curva = 5.0  # Exactly at threshold
    seg.load_tangente = 5.0

    result = _needs_maintenance(seg)
    assert result is True


def test_move_to_duration_override_replaces_base_move_days():
    """duration_override should control the date advance instead of seg.move_time_days."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.move_time_days != 7  # sanity: override differs from the base fixture value
    before = sim.simulation_date
    try:
        sim.move_to(seg, seg.end_station, action="v", duration_override=7)
        assert (sim.simulation_date - before).days == 7
        assert sim.steps[-1]["days"] == 7
    finally:
        seg.reset_maintenance()  # segments come from the cached default network, shared across tests


def test_move_to_duration_override_replaces_base_maintenance_days():
    """duration_override should also apply to the maintenance branch."""
    from src.models import ACTION_MAINTAIN

    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.maintenance_time_days != 11
    sim.machine.second_kld_installed = True  # force perform_maintenance regardless of direction
    before = sim.simulation_date
    try:
        sim.move_to(seg, seg.end_station, action=ACTION_MAINTAIN, duration_override=11)
        assert (sim.simulation_date - before).days == 11
        assert sim.steps[-1]["days"] == 11
    finally:
        seg.reset_maintenance()  # segments come from the cached default network, shared across tests


def test_move_to_without_duration_override_uses_segment_base():
    """No override -> unchanged behavior, duration comes from the segment."""
    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    before = sim.simulation_date
    try:
        sim.move_to(seg, seg.end_station, action="v")
        assert (sim.simulation_date - before).days == seg.move_time_days
    finally:
        seg.reset_maintenance()  # segments come from the cached default network, shared across tests


def test_maintain_curves_action_resets_only_curva_component():
    """ACTION_MAINTAIN_CURVES must not clear the tangente accumulator (regression for the
    latent bug where perform_maintenance() ignored which action triggered it)."""
    from src.models import ACTION_MAINTAIN_CURVES

    sim = Simulator()
    sim.init_machine("TRO", "TMI", start_year=2025)
    seg = sim.segments[0]
    seg.mtbt_threshold_curva = 1.0
    seg.mtbt_threshold_tangente = 1000.0
    seg.add_load(2.0)
    assert seg.maintenance_due_curva is True
    assert seg.maintenance_due_tangente is False

    sim.machine.second_kld_installed = True  # force perform_maintenance to run regardless of direction
    sim.move_to(seg, seg.end_station, action=ACTION_MAINTAIN_CURVES)

    assert seg.load_curva == 0.0
    assert seg.load_tangente == pytest.approx(2.0)


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
    if seg.mtbt_threshold_curva:
        seg.load_curva = seg.mtbt_threshold_curva + 1

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
    seg.mtbt_threshold_curva = 0
    seg.mtbt_threshold_tangente = 0
    seg.load_curva = 100  # Lots of load
    seg.load_tangente = 100

    # Segment with zero threshold DOES trigger maintenance (100 >= 0 is True):
    # _needs_maintenance treats an explicit 0 as configured (only `None` means
    # "no threshold set"), same as the pre-split single-field behavior.
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
    seg = Segment("A-B", start, end, length=10, mtbt_threshold_curva=10.0, mtbt_threshold_tangente=10.0)

    # add_load should accumulate on both components
    seg.add_load(3.0)
    assert seg.load_curva == pytest.approx(3.0)
    assert seg.load_tangente == pytest.approx(3.0)
    seg.add_load(2.5)
    assert seg.load_curva == pytest.approx(5.5)
    assert seg.load_tangente == pytest.approx(5.5)

    # add_mtbt is alias for add_load
    seg.add_mtbt(1.5)
    assert seg.load_curva == pytest.approx(7.0)
    assert seg.load_tangente == pytest.approx(7.0)
    # reset_maintenance should zero load and clear flag
    seg.load_curva = 12.0  # Over threshold
    seg.load_tangente = 12.0
    seg.maintenance_due_curva = True
    seg.maintenance_due_tangente = True
    seg.maintenance_due = True
    seg.reset_maintenance()
    assert seg.load_curva == 0.0
    assert seg.load_tangente == 0.0
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
