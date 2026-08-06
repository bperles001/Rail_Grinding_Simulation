import pytest

from src.models import GrinderMachine, Segment, Station


def _build_segment(threshold_curva: float = 10.0, threshold_tangente: float = 10.0) -> tuple[Station, Station, Segment]:
    start = Station("STA", can_turn=True)
    end = Station("STB")
    segment = Segment(
        name="STA-STB",
        start_station=start,
        end_station=end,
        length=12.5,
        mtbt_threshold_curva=threshold_curva,
        mtbt_threshold_tangente=threshold_tangente,
        move_time_days=2,
        maintenance_time_days=3,
    )
    return start, end, segment


def test_segment_registers_with_stations_and_allowed_movements():
    start, end, segment = _build_segment()
    assert segment in start.segments
    assert segment in end.segments
    assert (start.name, end.name) in segment.allowed_movements
    assert (end.name, start.name) in segment.allowed_movements


def test_add_load_applies_to_both_accumulators_and_flags_independently():
    _, _, segment = _build_segment(threshold_curva=5.0, threshold_tangente=100.0)
    segment.add_load(3)
    assert segment.maintenance_due_curva is False
    assert segment.maintenance_due_tangente is False
    assert segment.maintenance_due is False
    segment.add_load(2.5)
    assert segment.load_curva == pytest.approx(5.5)
    assert segment.load_tangente == pytest.approx(5.5)
    assert segment.maintenance_due_curva is True
    assert segment.maintenance_due_tangente is False
    assert segment.maintenance_due is True


def test_reset_maintenance_curva_only_leaves_tangente_accumulating():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=2.0)
    segment.add_load(2.0)
    assert segment.maintenance_due_curva is True
    assert segment.maintenance_due_tangente is True
    segment.reset_maintenance(component="curva")
    assert segment.load_curva == 0.0
    assert segment.maintenance_due_curva is False
    assert segment.load_tangente == pytest.approx(2.0)
    assert segment.maintenance_due_tangente is True
    assert segment.maintenance_due is True  # tangente still due


def test_reset_maintenance_both_clears_everything():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=2.0)
    segment.add_load(2.0)
    segment.reset_maintenance()
    assert segment.load_curva == 0.0
    assert segment.load_tangente == 0.0
    assert segment.maintenance_due is False


def test_grinder_machine_perform_maintenance_resets_requested_component():
    _, _, segment = _build_segment(threshold_curva=2.0, threshold_tangente=100.0)
    segment.add_load(2.0)
    grinder = GrinderMachine(front_car_position=segment, rear_car_position=segment, facing="Carregado", global_direction="carregado")
    assert segment.maintenance_due is True
    performed = grinder.perform_maintenance(segment, component="curva")
    assert performed is True
    assert segment.load_curva == 0.0
    assert segment.maintenance_due is False
    assert grinder.mode == "maintenance"
