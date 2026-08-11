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


def test_auto_planner_needs_maintenance_and_action_over_segment_tuple(tmp_path):
    from railroad_backend.services.auto_planner import _maintenance_action_for, _needs_maintenance
    from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, _destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments

    assert _needs_maintenance(segments) is False

    directional.add_load(20.0)  # only the directional's tangente threshold (20.0) is hit
    assert _needs_maintenance(segments) is True
    assert _maintenance_action_for(segments) == ACTION_MAINTAIN  # tangente due -> full maintain

    directional.reset_maintenance()
    singela.mtbt_threshold_curva = 5.0
    singela.add_load(5.0)  # only curva due, on the Singela this time
    assert _needs_maintenance(segments) is True
    assert _maintenance_action_for(segments) == ACTION_MAINTAIN_CURVES


def test_directional_segment_classifies_by_name_suffix_not_departure_station(tmp_path):
    """LP/LD (and C/V) segments are always Carregado/Vazio by identity, not
    by which station you're departing from -- a unidirectional segment can
    only ever be traveled from its own start, so the old start-station
    heuristic always returned CARREGADO for it, meaning global_direction
    could never match VAZIO after a Turn (regression reported 2026-08-07:
    maintenance became unavailable, everything showed 'move only')."""
    from railroad_backend.services.manual_planner import list_available_moves
    from src.simulator.core import _classify_directional_segment

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    directional = segments[-1]
    assert directional.name == "A-B-LD"
    assert _classify_directional_segment(directional, "A") == "VAZIO"

    # Facing B from A travels via A-B-LD (Vazio), so init_machine sets
    # global_direction accordingly -- move_to() itself never changes it,
    # only flip_global_direction() (Turn) does.
    sim.move_to(segments, destination, action="v")
    assert sim.current_station.name == "B"
    assert sim.machine.global_direction == "VAZIO"

    # Turn: the corridor back to A (via A-B-LP) must now be
    # maintenance-aligned, since LP is Carregado by identity and the machine
    # is now facing Carregado after the turn.
    sim.flip_global_direction()
    assert sim.machine.global_direction == "CARREGADO"

    options = list_available_moves(sim)
    back_to_a = next(o for o in options if o.destination == "A")
    assert back_to_a.segment_alignment["A-B-LP"] is True  # LP is Carregado, machine now faces Carregado

    sim.flip_global_direction()  # turn back to Vazio
    options = list_available_moves(sim)
    back_to_a = next(o for o in options if o.destination == "A")
    assert back_to_a.segment_alignment["A-B-LP"] is False  # LP is Carregado, machine faces Vazio


def test_move_to_maintain_segments_resets_only_the_chosen_leg(tmp_path):
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

    sim.machine.second_kld_installed = True
    sim.move_to(segments, destination, action=ACTION_MAINTAIN, maintain_segments=[directional])

    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0
    assert singela.load_curva == pytest.approx(10.0)  # untouched -- only the directional was chosen
    assert sim.steps[-1]["maintained_segments"] == [directional.name]
    # duration: maintenance_time_days (directional, 1) + move_time_days (Singela, 2) = 3
    assert sim.steps[-1]["days"] == 3


def test_move_to_maintain_segments_none_still_resets_everything(tmp_path):
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

    sim.machine.second_kld_installed = True
    sim.move_to(segments, destination, action=ACTION_MAINTAIN)  # maintain_segments omitted

    assert singela.load_curva == 0.0
    assert directional.load_curva == 0.0
    assert set(sim.steps[-1]["maintained_segments"]) == {"A-B", "A-B-LD"}
    # duration: maintenance_time_days for both: 3 (Singela) + 1 (directional) = 4
    assert sim.steps[-1]["days"] == 4


def test_init_machine_facing_agrees_with_move_time_classification(tmp_path):
    """init_machine's initial global_direction must be classified the same
    way move_to()/get_possible_moves() classify it later, or the machine can
    start out facing a direction that never matches its own facing segment
    (regression reported 2026-08-07: starting with facing set toward a -LD
    leg showed the corridor back as 'move only', maintenance never aligned,
    because init used the old start-station heuristic while moves used the
    new name-suffix one)."""
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    # Facing B from A travels the corridor via A-B-LD (Vazio by suffix).
    sim.init_machine("A", "B", start_year=2025)
    assert sim.machine.global_direction == "VAZIO"
    options = list_available_moves(sim)
    to_b = next(o for o in options if o.destination == "B")
    assert to_b.segments[-1] == "A-B-LD"
    # A-B (Singela, sem sufixo) classifica por heuristica start/end: partindo
    # de A, isso da CARREGADO -- que nao bate com o global_direction VAZIO
    # setado pelo facing inicial. A-B-LD classifica VAZIO por sufixo, que bate.
    assert to_b.segment_alignment == {"A-B": False, "A-B-LD": True}


def test_list_available_moves_reports_segment_tuple_for_trio(tmp_path):
    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    options = list_available_moves(sim)
    assert len(options) == 1
    assert options[0].segments == ("A-B", "A-B-LD")
    assert options[0].destination == "B"


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

    # Should reject above the 365-day cap (mirrors the UI widget's
    # max_value=365 -- found via the 2026-08-11 fuzz campaign: the engine
    # had no upper bound, only the form widget did, so an imported plan
    # could set an arbitrarily large wait and blow up timeline rendering)
    with pytest.raises(ValueError, match="at most 365"):
        sim.wait_days(366)

    # 365 itself is still valid (boundary)
    assert sim.wait_days(365) is True


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


def test_move_to_with_segment_actions_mixes_curva_and_completa(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.add_load(10.0)  # threshold 100/100 -- so "curva" nao teria zerado por acaso
    directional.add_load(10.0)  # threshold 5/20

    sim.machine.second_kld_installed = True  # elimina a variavel de alinhamento deste teste
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "curva", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert singela.load_curva == 0.0
    assert singela.load_tangente == 10.0  # so curva foi resetada
    assert directional.load_curva == 0.0
    assert directional.load_tangente == 0.0  # completa reseta os dois
    # duracao: maintenance_time_days dos dois, porque nenhum token e "none"
    assert result["duration"] == singela.maintenance_time_days + directional.maintenance_time_days
    assert sim.steps[-1]["maintained_segments"] == ["A-B", "A-B-LD"]


def test_move_to_with_segment_actions_none_skips_segment_entirely(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.add_load(10.0)
    directional.add_load(10.0)

    sim.machine.second_kld_installed = True
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert singela.load_curva == 10.0  # nao mantido, load intacto (so passou por cima)
    assert directional.load_curva == 0.0  # mantido
    # duracao: move_time_days da singela (nao mantida) + maintenance_time_days da directional
    assert result["duration"] == singela.move_time_days + directional.maintenance_time_days
    assert sim.steps[-1]["maintained_segments"] == ["A-B-LD"]


def test_move_to_with_segment_actions_always_performs_without_second_kld_misaligned(tmp_path):
    """Mudanca de comportamento central desta rodada: hoje, sem 2o KLD e
    desalinhado, a manutencao nao executa (performed=False, MTBT intacto).
    Com segment_actions, ela sempre executa -- so a leitura do KLD fica
    marcada como nao capturada."""
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments  # directional = A-B-LD, Vazio por sufixo
    directional.add_load(10.0)

    assert sim.machine.global_direction == "VAZIO"  # facing B via A-B-LD
    sim.machine.global_direction = "CARREGADO"  # forca desalinhamento com A-B-LD (Vazio)
    sim.machine.second_kld_installed = False

    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0  # MTBT reseta igual
    assert sim.steps[-1]["kld_reading"] == {"A-B-LD": False}  # sem leitura, mas o servico ocorreu


def test_move_to_with_segment_actions_records_true_when_aligned(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    assert sim.machine.global_direction == "VAZIO"  # A-B-LD e Vazio por sufixo: alinhado
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert sim.steps[-1]["kld_reading"] == {"A-B-LD": True}


def test_move_to_with_segment_actions_rejects_unknown_segment_name(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    with pytest.raises(ValueError, match="unknown segment"):
        sim.move_to(
            segments, destination, action=ACTION_MOVE,
            segment_actions={"NOT-A-REAL-SEGMENT": "completa"},
        )


def test_move_to_with_segment_actions_rejects_invalid_token(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    with pytest.raises(ValueError, match="must be one of"):
        sim.move_to(
            segments, destination, action=ACTION_MOVE,
            segment_actions={"A-B-LD": "tangente"},
        )


def test_move_to_with_segment_actions_completa_records_maintenance_action(tmp_path):
    """Regressao: passo com segment_actions "completa" ficava marcado como
    step["action"] == "move" (a classificacao so olhava o parametro `action`
    legado, nunca passado como maintain pelo manual_planner). Isso fazia a
    tabela de resultados e o timeline mostrarem manutencao real como
    movimento simples."""
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    sim.machine.second_kld_installed = True

    sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert sim.steps[-1]["action"] == "maintenance"


def test_move_to_with_segment_actions_curva_only_records_maintenance_curves_action(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    sim.machine.second_kld_installed = True

    sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "curva", "A-B-LD": "none"},
    )

    assert sim.steps[-1]["action"] == "maintenance_curves"


def test_move_to_reports_mtbt_after_curva_e_tangente(tmp_path):
    """mtbt_after_curva/tangente devem refletir o estado do segmento (`seg`,
    a perna mais especifica) DEPOIS da manutencao e do acumulo diario do
    proprio passo -- pedido do Bruno para substituir a coluna morta
    "mtbt_before" (sempre None, sobra do turn/wait) por um "MTBT depois"
    de verdade."""
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    directional.add_load(3.0)
    sim.machine.second_kld_installed = True

    sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    step = sim.steps[-1]
    # sem daily_map nesta rede de teste -- so o reset da manutencao conta
    assert step["mtbt_after_curva"] == 0.0
    assert step["mtbt_after_tangente"] == 0.0


def test_move_to_with_segment_actions_all_none_records_move_action(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    sim.machine.second_kld_installed = True

    sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "none"},
    )

    assert sim.steps[-1]["action"] == "move"
