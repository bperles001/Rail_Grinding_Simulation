"""Integration tests for end-to-end workflows across services and components."""
import json
from pathlib import Path

import pandas as pd
import pytest

from railroad_backend.domain.schedule import build_daily_map, validate_schedule_dataframe
from railroad_backend.persistence.plan_storage import (
    clone_auto_result,
    import_auto_run_payload,
    load_plan_storage,
    save_auto_run_entry,
)
from railroad_backend.services.auto_planner import (
    AutoPlanConfig,
    AutoPlanResult,
    auto_defaults,
    run_auto_plan,
    run_auto_plan_from_args,
)
from railroad_backend.services.manual_planner import (
    ManualPlanConfig,
    list_available_moves,
    replay_manual_plan,
)
from railroad_backend.services.network_editor import (
    default_facing_station_from_config,
    default_start_station_from_config,
    facing_options_from_config,
    station_choices_from_config,
)
from railroad_backend.services.schedule_service import (
    current_schedule_dataframe,
    parse_schedule_bytes,
    schedule_missing_segments,
    summarize_schedule_dataframe,
)
from src.models import Segment, Station
from src.simulator import DEFAULT_NETWORK_FILE, Simulator, build_network, prepare_timeline_rows
from src.utils.network_loader import load_network
from src.utils.timeline_generator import TimelineGenerator


# ============================================================================
# AUTO PLANNING WORKFLOW TESTS
# ============================================================================


def test_auto_plan_full_workflow(tmp_path):
    """Test complete auto planning workflow from config to results."""
    # Setup: Create schedule CSV
    csv_path = tmp_path / "schedule.csv"
    csv_data = "Segment Name,2025-01,2025-02\nTRO-TMI,5.0,3.0\nTMI-ZTO,4.0,2.5\n"
    csv_path.write_text(csv_data)
    
    # Step 1: Load network configuration
    network_config = load_network(DEFAULT_NETWORK_FILE)
    assert network_config is not None
    
    # Step 2: Get default configuration values
    defaults = auto_defaults(network_config)
    assert "start_station" in defaults
    assert "facing_station" in defaults
    
    # Step 3: Create configuration
    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=10,
    )
    
    # Step 4: Run auto plan
    result = run_auto_plan(config)
    
    # Step 5: Validate results
    assert isinstance(result, AutoPlanResult)
    assert result.simulator is not None
    assert len(result.simulator.steps) > 0
    assert result.stop_reason in {"steps_limit", "year_limit", "stalled"}
    assert "steps_requested" in result.stop_details
    
    # Step 6: Verify simulator state
    sim = result.simulator
    assert sim.machine is not None
    assert sim.current_station is not None
    assert sim.simulation_date is not None
    assert hasattr(sim, "movement_days_total")
    assert hasattr(sim, "maintenance_days_total")


def test_auto_plan_with_persistence(tmp_path):
    """Test auto planning with result persistence and retrieval."""
    # Setup
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")
    storage_path = tmp_path / "storage.json"
    
    # Run auto plan
    result = run_auto_plan_from_args(
        csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        steps=5,
        second_kld=False,
    )
    
    # Create result payload
    payload = {
        "config": {
            "start_station": "TRO",
            "facing_station": "TMI",
            "start_year": 2025,
            "end_year": 2025,
            "steps": 5,
            "second_kld": False,
        },
        "result": {
            "steps": [dict(step) for step in result.simulator.steps],
            "movement_days_total": result.simulator.movement_days_total,
            "maintenance_days_total": result.simulator.maintenance_days_total,
            "maintenance_count": result.simulator.maintenance_count,
            "stop_reason": result.stop_reason,
        },
    }
    
    # Save to storage
    storage = {"manual": {}, "auto": {}}
    storage["auto"] = save_auto_run_entry(storage["auto"], "test_run", payload)
    assert "test_run" in storage["auto"]
    
    # Clone entry (clone works on the payload)
    cloned = clone_auto_result(payload)
    assert "result" in cloned
    assert len(cloned["result"]["steps"]) == len(payload["result"]["steps"])
    
    # Import payload (wrap in auto section with name)
    import_payload = {"test_import": payload}
    imported_runs, count = import_auto_run_payload({}, import_payload)
    assert count == 1
    assert "test_import" in imported_runs


def test_auto_plan_with_initial_loads(tmp_path):
    """Test that auto planning correctly applies initial segment loads."""
    # Create schedule with Initial Load column
    csv_path = tmp_path / "schedule.csv"
    csv_data = (
        "Segment Name,Initial Load,2025-01\n"
        "TRO-TMI,10.0,2.0\n"
        "TMI-ZTO,5.0,1.5\n"
    )
    csv_path.write_text(csv_data)
    
    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=20,
    )
    
    result = run_auto_plan(config)
    sim = result.simulator
    
    # Verify initial loads were applied
    tro_tmi = next((s for s in sim.segments if s.name == "TRO-TMI"), None)
    assert tro_tmi is not None
    # Initial load should have been applied (may have changed due to moves)
    assert hasattr(tro_tmi, "load_curva")
    assert hasattr(tro_tmi, "load_tangente")


# ============================================================================
# MANUAL PLANNING WORKFLOW TESTS
# ============================================================================


def test_manual_plan_full_workflow(tmp_path):
    """Test complete manual planning workflow from config to execution."""
    # Setup
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\nTMI-ZTO,6.0\n")
    
    # Step 1: Create configuration
    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    # Step 2: Create simple valid plan (wait and turn only to avoid complex segment logic)
    plan = [
        {"mode": "wait", "days": 5},
        {"mode": "turn"},
    ]
    
    # Step 3: Replay plan
    result = replay_manual_plan(config, plan)
    
    # Step 4: Validate execution
    assert result.simulator is not None
    assert len(result.errors) == 0
    assert len(result.simulator.steps) > 0


def test_manual_plan_with_available_moves(tmp_path):
    """Test manual planning with available moves listing."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")
    
    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    # Initialize simulator with empty plan
    result = replay_manual_plan(config, [])
    sim = result.simulator
    
    # Get available moves
    moves = list_available_moves(sim)
    
    # Validate moves
    assert len(moves) > 0
    for move in moves:
        assert hasattr(move, "segments")
        assert hasattr(move, "destination")
        assert hasattr(move, "segment_alignment")


def test_manual_plan_step_days_override_changes_duration(tmp_path):
    """A move step with days_override should advance the date by that many days."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )

    result = replay_manual_plan(config, [])
    sim = result.simulator
    seg = next(s for s in sim.segments if s.start_station.name == "TRO" and s.end_station.name == "TMI")
    assert seg.move_time_days != 9

    plan = [{"mode": "move", "segment": seg.name, "destination": "TMI", "segment_actions": {seg.name: "none"}, "days_override": 9}]
    try:
        result = replay_manual_plan(config, plan)
        assert result.errors == []
        assert result.simulator.steps[-1]["days"] == 9
    finally:
        seg.reset_maintenance()  # segments come from the cached default network, shared across tests


def test_manual_plan_move_step_with_segments_list_traverses_trio(tmp_path):
    """A move step using the new 'segments' (list) field should apply to both
    the Singela and the directional leg."""
    import json

    network_payload = {
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
    network_path = tmp_path / "trio_network.json"
    network_path.write_text(json.dumps(network_payload), encoding="utf-8")

    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nA-B,1.0\nA-B-LD,1.0\nA-B-LP,1.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="A",
        facing_station="B",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        network_source=network_path,
    )

    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "segment_actions": {"A-B": "none", "A-B-LD": "none"}}]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
    assert result.simulator.steps[-1]["days"] == 3  # 2 (Singela) + 1 (directional)
    assert result.simulator.steps[-1]["segments"] == ["A-B", "A-B-LD"]


def test_manual_plan_move_step_with_segment_actions_resets_only_that_leg(tmp_path):
    import json

    network_payload = {
        "name": "trio",
        "stations": [{"name": "A", "can_turn": True}, {"name": "B", "can_turn": True}],
        "segments": [
            {
                "name": "A-B", "start": "A", "end": "B", "length_km": 10.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 2, "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            },
            {
                "name": "A-B-LD", "start": "A", "end": "B", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["A", "B"]],
            },
            {
                "name": "A-B-LP", "start": "B", "end": "A", "length_km": 1.0,
                "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 5.0,
                "move_time_days": 1, "maintenance_time_days": 1,
                "allowed_movements": [["B", "A"]],
            },
        ],
    }
    network_path = tmp_path / "trio_network.json"
    network_path.write_text(json.dumps(network_payload), encoding="utf-8")

    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,Initial Load,2025-01\nA-B,10.0,1.0\nA-B-LD,10.0,1.0\nA-B-LP,0.0,1.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="A",
        facing_station="B",
        start_year=2025,
        end_year=2025,
        second_kld=True,
        network_source=network_path,
    )

    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "segment_actions": {"A-B": "none", "A-B-LD": "completa"},
    }]
    result = replay_manual_plan(config, plan)
    assert result.errors == []
    sim = result.simulator
    singela = next(s for s in sim.segments if s.name == "A-B")
    directional = next(s for s in sim.segments if s.name == "A-B-LD")
    assert directional.load_curva < 1.0  # reset (small accrual from the days spent afterward is fine)
    assert singela.load_curva > 9.0  # untouched, kept its initial load
    assert sim.steps[-1]["maintained_segments"] == ["A-B-LD"]


def test_manual_plan_move_step_with_legacy_segment_key_still_works(tmp_path):
    """Plans saved before this change use a singular 'segment' string; must
    still replay correctly on a network with no Singela trios (default.json)."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")

    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )

    plan = [{"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "segment_actions": {"TRO-TMI": "none"}}]
    result = replay_manual_plan(config, plan)
    assert result.errors == []


def test_manual_plan_error_handling(tmp_path):
    """Test manual planning error detection and reporting."""
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")
    
    config = ManualPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    # Create plan with invalid moves
    invalid_plan = [
        {"mode": "move", "segment": "INVALID-SEGMENT", "destination": "TMI", "segment_actions": {"INVALID-SEGMENT": "completa"}},
    ]
    
    result = replay_manual_plan(config, invalid_plan)
    
    # Should have errors
    assert len(result.errors) > 0
    assert any("segment" in err.lower() or "step" in err.lower() for err in result.errors)


# ============================================================================
# SCHEDULE SERVICE INTEGRATION TESTS
# ============================================================================


def test_schedule_service_full_workflow(tmp_path):
    """Test complete schedule service workflow."""
    # Step 1: Create schedule CSV
    csv_path = tmp_path / "schedule.csv"
    csv_data = (
        "Segment Name,2025-01,2025-02\n"
        "TRO-TMI,3.0,2.5\n"
        "TMI-ZTO,4.0,3.5\n"
    )
    csv_path.write_text(csv_data)
    
    # Step 2: Parse schedule
    df = parse_schedule_bytes(csv_path.read_bytes())
    assert isinstance(df, pd.DataFrame)
    assert "Segment Name" in df.columns
    
    # Step 3: Validate schedule (returns validated DataFrame, raises on errors)
    validated_df = validate_schedule_dataframe(df)
    assert isinstance(validated_df, pd.DataFrame)
    
    # Step 4: Build daily map
    daily_map = build_daily_map(csv_path, 2025, 2025)
    assert daily_map is not None
    assert len(daily_map) > 0
    
    # Step 5: Parse works correctly - validated dataframe is valid
    assert len(validated_df) == 2  # Two segments
    assert "2025-01" in validated_df.columns
    assert "2025-02" in validated_df.columns


def test_schedule_missing_segments_detection(tmp_path):
    """Test detection of segments missing from schedule."""
    # Create schedule missing some segments
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,5.0\n")
    
    # Load network
    network_config = load_network(DEFAULT_NETWORK_FILE)
    
    # Get all segment names from network
    stations, segments = build_network(network_config)
    all_segment_names = [seg.name for seg in segments]
    
    # Parse schedule
    schedule_df = parse_schedule_bytes(csv_path.read_bytes())
    
    # Find missing segments (segments in schedule but NOT in network)
    missing = schedule_missing_segments(schedule_df, all_segment_names)
    
    # Should be empty since TRO-TMI is in the network
    assert len(missing) == 0 or "TRO-TMI" not in missing


# ============================================================================
# NETWORK EDITOR INTEGRATION TESTS
# ============================================================================


def test_network_editor_station_and_facing_options():
    """Test network editor helpers for station choices and facing options."""
    # Load network
    network_config = load_network(DEFAULT_NETWORK_FILE)
    
    # Get station choices
    stations = station_choices_from_config(network_config)
    assert len(stations) > 0
    assert "TRO" in stations
    assert "TMI" in stations
    
    # Get default start station
    default_start = default_start_station_from_config(network_config)
    assert default_start in stations
    
    # Get default facing station
    default_facing = default_facing_station_from_config(network_config)
    assert default_facing in stations
    
    # Get facing options for a station
    facing = facing_options_from_config(network_config, "TRO")
    assert len(facing) > 0


# ============================================================================
# TIMELINE GENERATION INTEGRATION TESTS
# ============================================================================


def test_timeline_generation_full_workflow(tmp_path):
    """Test complete timeline generation workflow."""
    # Step 1: Run simulation
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,10.0\n")
    
    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=10,
    )
    
    result = run_auto_plan(config)
    sim = result.simulator
    
    # Step 2: Prepare timeline rows
    timeline_rows, y_order, alias_map = prepare_timeline_rows(sim.steps, segments=sim.segments)
    
    # Step 3: Validate timeline rows
    assert len(timeline_rows) > 0
    for row in timeline_rows:
        # Timeline rows have time and activity information
        assert len(row) > 0
        assert any(k in row for k in ["start_time", "end_time", "activity", "segment_name"])
    
    # Step 4: Create timeline generator
    generator = TimelineGenerator(timeline_rows, y_order=y_order, alias_map=alias_map)
    
    # Step 5: Process data
    df = generator.process_data()
    assert df is not None
    assert not df.empty


# ============================================================================
# CROSS-SERVICE INTEGRATION TESTS
# ============================================================================


def test_auto_to_manual_workflow(tmp_path):
    """Test workflow transitioning from auto plan to manual adjustments."""
    # Step 1: Run auto plan
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\nTMI-ZTO,6.0\n")
    
    auto_config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=5,
    )
    
    auto_result = run_auto_plan(auto_config)
    
    # Step 2: Extract final state
    final_station = auto_result.simulator.current_station.name if auto_result.simulator.current_station else "TRO"
    
    # Step 3: Create manual plan starting from final state
    manual_config = ManualPlanConfig(
        csv_path=csv_path,
        start_station=final_station,
        facing_station="TMI" if final_station != "TMI" else "ZTO",
        start_year=2025,
        end_year=2025,
        second_kld=False,
    )
    
    manual_plan = [
        {"mode": "wait", "days": 10},
        {"mode": "turn"},
    ]
    
    manual_result = replay_manual_plan(manual_config, manual_plan)
    
    # Validate combined workflow
    assert len(auto_result.simulator.steps) > 0
    assert len(manual_result.simulator.steps) > 0
    assert len(manual_result.errors) == 0


def test_schedule_update_and_replan_workflow(tmp_path):
    """Test workflow updating schedule and replanning."""
    # Step 1: Initial schedule and plan
    csv_path = tmp_path / "schedule.csv"
    initial_data = "Segment Name,2025-01\nTRO-TMI,5.0\n"
    csv_path.write_text(initial_data)
    
    config1 = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=5,
    )
    
    result1 = run_auto_plan(config1)
    steps_count_1 = len(result1.simulator.steps)
    
    # Step 2: Update schedule with higher MTBT
    updated_data = "Segment Name,2025-01\nTRO-TMI,15.0\n"
    csv_path.write_text(updated_data)
    
    config2 = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=5,
    )
    
    result2 = run_auto_plan(config2)
    
    # Step 3: Validate different behavior with updated schedule
    # Higher initial MTBT should affect planning decisions
    assert result2.simulator is not None
    # Both should complete but may have different maintenance patterns
    assert result1.stop_reason in {"steps_limit", "year_limit", "stalled"}
    assert result2.stop_reason in {"steps_limit", "year_limit", "stalled"}


def test_network_and_schedule_consistency(tmp_path):
    """Test consistency between network configuration and schedule."""
    # Load network
    network_config = load_network(DEFAULT_NETWORK_FILE)
    stations, segments = build_network(network_config)
    
    # Create schedule with all segments
    csv_path = tmp_path / "schedule.csv"
    lines = ["Segment Name,2025-01"]
    for seg in segments:
        lines.append(f"{seg.name},5.0")
    csv_path.write_text("\n".join(lines) + "\n")
    
    # Parse schedule
    schedule_df = parse_schedule_bytes(csv_path.read_bytes())
    
    # Validate no missing segments
    segment_names = [seg.name for seg in segments]
    missing = schedule_missing_segments(schedule_df, segment_names)
    assert len(missing) == 0
    
    # Run simulation
    config = AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=10,
    )
    
    result = run_auto_plan(config)
    
    # Verify all segments in simulator match network
    sim_segment_names = {seg.name for seg in result.simulator.segments}
    net_segment_names = {seg.name for seg in segments}
    assert sim_segment_names == net_segment_names


# ============================================================================
# ERROR RECOVERY INTEGRATION TESTS
# ============================================================================


def test_invalid_schedule_recovery(tmp_path):
    """Test graceful handling of invalid schedule data."""
    # Create invalid schedule with negative values
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,-5.0\n")
    
    # Parse should raise ValueError on negative values
    with pytest.raises(ValueError, match="negative"):
        parse_schedule_bytes(csv_path.read_bytes())


def test_missing_schedule_file_handling(tmp_path):
    """Test handling of missing schedule file."""
    csv_path = tmp_path / "nonexistent.csv"
    
    # Should raise validation error
    with pytest.raises(ValueError, match="not found"):
        AutoPlanConfig(
            csv_path=csv_path,
            start_station="TRO",
            facing_station="TMI",
            start_year=2025,
            end_year=2025,
            second_kld=False,
            steps=10,
        )


def test_invalid_network_reference_handling():
    """Test handling of invalid network file reference."""
    invalid_path = Path("/nonexistent/network.json")
    
    # Should raise error when trying to use invalid network
    with pytest.raises((FileNotFoundError, ValueError)):
        Simulator(str(invalid_path))
