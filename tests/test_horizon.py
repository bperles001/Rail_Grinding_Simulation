"""Tests for the rolling-horizon due-candidate projection helper."""
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.horizon import project_due_candidates


def _config(tmp_path: Path, csv_data: str) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text(csv_data)
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_already_due_segment_has_zero_days_until_due(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,8.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 1.0
    seg.load_curva = 5.0
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next(c for c in candidates if c.segment_name == "TRO-TMI")
    assert match.days_until_due == 0


def test_segment_outside_horizon_is_excluded(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,0.1\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 1000.0
    seg.mtbt_threshold_tangente = 1000.0
    candidates = project_due_candidates(sim, horizon_days=5)
    assert not any(c.segment_name == "TRO-TMI" for c in candidates)
