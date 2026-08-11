import json

import pandas as pd
import pytest

from src.models import Segment, Station
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
        {"segment": "TRO-TMI", "action": "move", "start": "2025-01-01", "end": "2025-01-05", "mtbt_before_curva": 10.0, "mtbt_before_tangente": 10.0},
        {"segment": "TRO-TMI", "action": "maintenance", "start": "2025-01-05", "end": "2025-01-10", "mtbt_before_curva": 16.0, "mtbt_before_tangente": 16.0},
        {"segment": "TRO-TMI", "action": "wait", "start": "2025-01-10", "end": "2025-01-12"},
        {"segment": "TRO-TMI", "action": "turn", "start": "2025-01-12", "end": "2025-01-13"},
    ]
    timeline_rows, y_order, alias_map = prepare_timeline_rows(steps, segments=segments)
    assert timeline_rows, "Timeline rows should not be empty."
    generator = TimelineGenerator(timeline_rows, y_order=y_order, alias_map=alias_map)
    df = generator.process_data()
    assert generator.df is not None and not generator.df.empty
    assert df is generator.df


def test_prepare_timeline_rows_reports_worst_case_curva_tangente_mtbt():
    """Regressao: apos o split de MTBT curva/tangente, prepare_timeline_rows
    continuava lendo os campos antigos (seg.mtbt_threshold, step['mtbt_before'])
    que nao existem mais -- toda linha saia com threshold/before sempre None,
    entao o timeline nunca distinguia curva de tangente (pareciam "iguais").
    O valor exibido deve ser o "pior caso" (maior razao carga/limite), mesma
    regra ja adotada para a cor da barra (decisoes.md 2026-08-06)."""
    sta_a = Station("A")
    sta_b = Station("B")
    seg = Segment(
        "A-B", sta_a, sta_b,
        mtbt_threshold_curva=10.0, mtbt_threshold_tangente=100.0,
    )
    steps = [{
        "segment": "A-B", "action": "maintenance",
        "start": "2026-01-01", "end": "2026-01-02",
        # curva: 8/10 = 0.8 : tangente: 50/100 = 0.5 -- curva e o pior caso
        "mtbt_before_curva": 8.0, "mtbt_before_tangente": 50.0,
    }]
    rows, _y_order, _alias = prepare_timeline_rows(steps, segments=[seg])
    assert rows[0]["mtbt_before"] == 8.0
    assert rows[0]["mtbt_threshold"] == 10.0


def test_prepare_timeline_rows_collapses_corridor_step_to_sb_key():
    """Regressao do redesenho: a linha de um passo com Singela+ramal (ex.
    segments=["A-B", "A-B-LD"]) deve ser rotulada pelo par de estacoes (SB),
    nao mais pelo nome joined dos segmentos -- e' isso que colapsa Singela/
    LP/LD numa linha so no timeline."""
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "move",
        "maintained_segments": [],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["step"] == "A-B"


def test_prepare_timeline_rows_direction_vazio_when_ld_maintained():
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "maintenance",
        "maintained_segments": ["A-B", "A-B-LD"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "vazio"


def test_prepare_timeline_rows_direction_carregado_when_only_singela_maintained():
    report = [{
        "segment": "A-B", "segments": ["A-B"], "action": "maintenance",
        "maintained_segments": ["A-B"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-02",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "carregado"


def test_prepare_timeline_rows_direction_carregado_when_lp_maintained():
    report = [{
        "segment": "A-B-LP", "segments": ["A-B", "A-B-LP"], "action": "maintenance_curves",
        "maintained_segments": ["A-B-LP"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-02",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "carregado"


def test_prepare_timeline_rows_direction_none_when_no_maintenance():
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "move",
        "maintained_segments": [],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] is None


def test_prepare_timeline_rows_y_order_dedupes_by_sb_key():
    """timeline_order/segments podem trazer "A-B", "A-B-LP", "A-B-LD" como
    3 entradas -- o y_order final deve ter "A-B" uma vez so, na posicao da
    primeira ocorrencia."""
    sta_a = Station("A")
    sta_b = Station("B")
    seg_singela = Segment("A-B", sta_a, sta_b)
    seg_lp = Segment("A-B-LP", sta_b, sta_a)
    seg_ld = Segment("A-B-LD", sta_a, sta_b)
    rows, y_order, _alias = prepare_timeline_rows(
        [], segments=[seg_singela, seg_lp, seg_ld], timeline_order=None,
    )
    assert y_order == ["A-B"]


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


def test_segment_status_rows_reports_real_load_curva_and_tangente():
    """Regressao: apos o split de MTBT curva/tangente, _segment_status_rows
    lia getattr(seg, "load", 0) -- atributo que nao existe mais no Segment
    (virou load_curva/load_tangente) -- entao "Segment load snapshot" saia
    sempre zerado, mesmo com carga real acumulada."""
    from streamlit_app import _segment_status_rows

    sta_a = Station("A")
    sta_b = Station("B")
    seg = Segment("A-B", sta_a, sta_b)
    seg.add_load(7.5)

    sim = Simulator()
    sim.segments = [seg]
    sim.maintenance_log = []

    rows = _segment_status_rows(sim)
    assert rows[0]["Load Curva"] == 7.5
    assert rows[0]["Load Tangente"] == 7.5


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
