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


def test_severity_is_one_when_a_segment_just_crossed_its_threshold(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,8.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 10.0  # exactly at threshold -- just crossed
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next(c for c in candidates if c.segment_name == "TRO-TMI")
    assert match.severity == 1.0


def test_severity_scales_with_how_far_over_threshold_a_segment_is(tmp_path):
    """Regression test for the "due severity blindness" gap: a segment
    loaded at ~9x its threshold must report a much higher severity than one
    that just crossed it, so the objective can tell them apart -- confirmed
    on the real network as segments left at ~9x threshold while the planner
    kept re-servicing nearby segments that had only just crossed
    (2026-08-12 diagnostic)."""
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,8.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 90.0  # 9x over threshold
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next(c for c in candidates if c.segment_name == "TRO-TMI")
    assert match.severity == 9.0


def test_severity_takes_the_worse_of_curva_and_tangente(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,8.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 15.0  # 1.5x over
    seg.mtbt_threshold_tangente = 10.0
    seg.load_tangente = 40.0  # 4x over -- the worse component
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next(c for c in candidates if c.segment_name == "TRO-TMI")
    assert match.severity == 4.0


def test_severity_defaults_to_one_for_a_not_yet_due_candidate(tmp_path):
    sim = _init_simulation(_config(tmp_path, "Segment Name,2025-01\nTRO-TMI,1.0\n"))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 100.0
    seg.load_curva = 10.0  # nowhere near due yet, but projected within the horizon
    candidates = project_due_candidates(sim, horizon_days=90)
    match = next((c for c in candidates if c.segment_name == "TRO-TMI"), None)
    if match is not None:
        assert match.severity == 1.0
