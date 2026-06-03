import pytest

from src.models import GrinderMachine, Segment, Station


def _build_segment(mtbt_threshold: float = 10.0) -> tuple[Station, Station, Segment]:
    start = Station("STA", can_turn=True)
    end = Station("STB")
    segment = Segment(
        name="STA-STB",
        start_station=start,
        end_station=end,
        length=12.5,
        mtbt_threshold=mtbt_threshold,
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


def test_segment_load_triggers_maintenance_flag():
    _, _, segment = _build_segment(mtbt_threshold=5.0)
    segment.add_load(3)
    assert segment.maintenance_due is False
    segment.add_load(2.5)
    assert segment.load == pytest.approx(5.5)
    assert segment.maintenance_due is True


def test_grinder_machine_perform_maintenance_resets_load():
    _, _, segment = _build_segment(mtbt_threshold=2.0)
    segment.add_load(2.0)
    grinder = GrinderMachine(front_car_position=segment, rear_car_position=segment, facing="Carregado", global_direction="carregado")
    assert segment.maintenance_due is True
    performed = grinder.perform_maintenance(segment)
    assert performed is True
    assert segment.load == 0.0
    assert segment.maintenance_due is False
    assert grinder.mode == "maintenance"
