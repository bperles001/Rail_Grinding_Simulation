import json

import pandas as pd
import pytest

from src.simulator import DEFAULT_NETWORK_FILE, Simulator, build_network, prepare_timeline_rows
from src.utils.network_loader import NetworkConfigError, load_network
from src.utils.timeline_generator import TimelineGenerator, TimelinePlot
from streamlit_app import DEFAULT_SCHEDULE, run_auto_plan
from railroad_backend.domain.schedule import validate_schedule_dataframe


def test_simulator_import_and_init():
    """Basic smoke test: Simulator can be instantiated and initialized."""
    sim = Simulator()
    sim.init_machine(start_station_name="TRO", facing_station_name="TMI", start_year=2025)
    assert sim.machine is not None
    assert sim.current_station.name == "TRO"


def test_flip_turn_allowed_at_TRO():
    sim = Simulator()
    sim.init_machine(start_station_name="TRO", facing_station_name="TMI", start_year=2025)
    # Flip global direction should be allowed at TRO
    assert sim.flip_global_direction() is True
    assert sim.machine.facing in ("Carregado", "Vazio")


def test_second_kld_allows_reverse_maintenance():
    sim = Simulator()
    # Start at TMI facing ZTO (global CARREGADO)
    sim.init_machine(start_station_name="TMI", facing_station_name="ZTO", start_year=2025)
    # Move forward TMI->ZTO to set current_station to ZTO
    seg_fwd = next(s for s in sim.segments if s.start_station.name == "TMI" and s.end_station.name == "ZTO")
    sim.move_to(seg_fwd, seg_fwd.end_station, action="v")
    # Now at ZTO, try to perform maintenance moving back to TMI (reverse)
    # Without Second KLD this would be blocked; with it allowed.
    sim.machine.second_kld_installed = True
    res = sim.move_to(seg_fwd, seg_fwd.start_station, action="m")
    assert res["performed"] is True


def test_run_auto_plan_generates_steps(tmp_path):
    schedule_copy = tmp_path / "mtbt_schedule.csv"
    schedule_copy.write_bytes(DEFAULT_SCHEDULE.read_bytes())
    sim = run_auto_plan(
        schedule_copy,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        steps=8,
        second_kld=False,
    )
    assert len(sim.steps) > 0
    assert sim.stop_reason in {"steps_limit", "year_limit", "stalled"}


def test_prepare_timeline_rows_and_generator():
    _, segments = build_network()
    steps = [
        {"segment": "TRO-TMI", "action": "move", "start": "2025-01-01", "end": "2025-01-05", "mtbt_before": 10.0},
        {"segment": "TRO-TMI", "action": "maintenance", "start": "2025-01-05", "end": "2025-01-10", "mtbt_before": 16.0},
        {"segment": "TRO-TMI", "action": "wait", "start": "2025-01-10", "end": "2025-01-12"},
        {"segment": "TRO-TMI", "action": "turn", "start": "2025-01-12", "end": "2025-01-13"},
    ]
    timeline_rows, y_order, alias_map = prepare_timeline_rows(steps, segments=segments)
    assert timeline_rows, "Timeline rows should not be empty."
    generator = TimelineGenerator(timeline_rows, y_order=y_order, alias_map=alias_map)
    df = generator.process_data()
    assert generator.df is not None and not generator.df.empty
    assert df is generator.df


def test_timeline_generator_returns_structured_plot():
    _, segments = build_network()
    steps = [
        {"segment": "TRO-TMI", "action": "move", "start": "2025-01-01", "end": "2025-01-03"},
        {"segment": "TRO-TMI", "action": "maintenance", "start": "2025-01-03", "end": "2025-01-05"},
    ]
    timeline_rows, y_order, alias_map = prepare_timeline_rows(steps, segments=segments)
    generator = TimelineGenerator(timeline_rows, y_order=y_order, alias_map=alias_map)
    generator.process_data()
    plot = generator.create_timeline_plot()
    assert isinstance(plot, TimelinePlot)
    assert plot.figure is generator.fig
    assert plot.axes is generator.ax
    assert plot.dataframe is generator.df


def test_validate_schedule_dataframe_rejects_negative_values():
    df = pd.DataFrame(
        {
            "Segment Name": ["SEG"],
            "2025-01": [10],
            "2025-02": [-5],
        }
    )
    with pytest.raises(ValueError):
        validate_schedule_dataframe(df)


def test_load_network_default_snapshot():
    config = load_network(DEFAULT_NETWORK_FILE)
    assert "TRO" in config.stations
    segment_names = {seg.name for seg in config.segments}
    assert "TRO-TMI" in segment_names


def test_load_network_rejects_unknown_station(tmp_path):
    bad_config = {
        "name": "invalid",
        "stations": [
            {"name": "A"},
        ],
        "segments": [
            {
                "name": "A-B",
                "start": "A",
                "end": "B",
                "length_km": 1,
                "mtbt_threshold_curva": 1,
                "mtbt_threshold_tangente": 1,
                "move_time_days": 1,
                "maintenance_time_days": 1,
            }
        ],
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(bad_config))
    with pytest.raises(NetworkConfigError):
        load_network(path)
