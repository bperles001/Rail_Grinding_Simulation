"""Shared evaluation harness for the overnight Auto Planner algorithm
search. Isolated from src/ -- imports the real Simulator/strategy classes
read-only, drives them itself, never registers anything, never edits a
shipped file.

Two run modes:
- run_fast(): fixed SIMULATED CALENDAR-DAY horizon (not step count) --
  cheap, for broad search across many candidates in one night.
- run_full(): runs to the real year_limit (2027-12-31), same stopping
  rule as scripts/compare_auto_strategies.py -- reserved for the small
  number of finalist candidates, since it costs much more compute.

Both report `pct_maintenance` = maintenance_days / total_days, the exact
metric the manual-plan comparison (Task 6, 2026-09-05) judged strategies
against: manual = 92.7%, Greedy = 14.1%, ILP/SA = 55.8-75.1%,
MCTS(default, 400-step cap) = 58.9% (that MCTS number is NOT an
apples-to-apples comparison against the others -- it stopped at
steps_limit with only 701 simulated days covered, vs ~730 for everyone
else, which is exactly why this harness compares by calendar day instead
of step count).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from railroad_backend.services.auto_planner import (  # noqa: E402
    AutoPlanConfig,
    _execute_decision,
    _init_simulation,
)
from railroad_backend.services.auto_planner_strategies.base import AutoPlanStrategy  # noqa: E402

NETWORK_FILE = REPO / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE_CSV = REPO / "data" / "mtbt_schedule.csv"

COMMON_CONFIG_KWARGS: Dict[str, Any] = dict(
    csv_path=SCHEDULE_CSV,
    start_station="ZTO",
    facing_station="ZCZ",
    start_year=2026,
    end_year=2027,
    second_kld=True,
    network_source=NETWORK_FILE,
)

# Reference numbers from the Task 6 study (docs/2026-08-11-auto-planner-
# algorithm-study.md, run 2026-09-05/06) -- NOT recomputed here, kept as a
# fixed comparison point since regenerating them costs significant compute
# and they haven't changed. The MCTS row there is flagged unfair (see
# module docstring) and superseded by whatever calendar-day-fair MCTS
# candidates this search finds.
REFERENCE_METRICS: Dict[str, Dict[str, Any]] = {
    "manual_plan_real": {"pct_maintenance": 333 / 359, "segments_over_threshold_at_end": 25, "total_days": 359, "note": "88-step real plan, own horizon (not 2026-2027 full range)"},
    "greedy": {"pct_maintenance": 103 / 731, "segments_over_threshold_at_end": 92, "total_days": 731},
    "rolling_ilp_best(window=90d)": {"pct_maintenance": 409 / 730, "segments_over_threshold_at_end": 41, "total_days": 730},
    "simulated_annealing_best(window=90d,seed=2)": {"pct_maintenance": 548 / 730, "segments_over_threshold_at_end": 21, "total_days": 730},
    "mcts_default_UNFAIR_stepcapped": {"pct_maintenance": 413 / 701, "segments_over_threshold_at_end": 26, "total_days": 701, "note": "stopped at steps_limit (400), NOT year_limit -- not directly comparable, see module docstring"},
}


def _metrics_dict(sim, stop_reason: str, steps_used: int) -> Dict[str, Any]:
    idle = getattr(sim, "idle_days_total", 0)
    total = sim.movement_days_total + sim.maintenance_days_total + idle
    over_threshold = 0
    for seg in sim.segments:
        if seg.mtbt_threshold_curva and seg.load_curva >= seg.mtbt_threshold_curva:
            over_threshold += 1
        if seg.mtbt_threshold_tangente and seg.load_tangente >= seg.mtbt_threshold_tangente:
            over_threshold += 1
    return {
        "stop_reason": stop_reason,
        "steps_used": steps_used,
        "maintenance_count": sim.maintenance_count,
        "movement_days": sim.movement_days_total,
        "maintenance_days": sim.maintenance_days_total,
        "idle_days": idle,
        "total_days": total,
        "pct_maintenance": (sim.maintenance_days_total / total) if total else 0.0,
        "segments_over_threshold_at_end": over_threshold,
    }


def run_fast(
    make_strategy: Callable[[], AutoPlanStrategy],
    *,
    max_days: int = 180,
    max_steps: int = 250,
) -> Dict[str, Any]:
    """Cheap proxy-metric run: stop at `max_days` of simulated calendar
    time (or `max_steps`, or a stall), whichever comes first. Use this for
    broad candidate search."""
    config = AutoPlanConfig(**COMMON_CONFIG_KWARGS, steps=0)
    sim = _init_simulation(config)
    strategy = make_strategy()
    start_date = sim.simulation_date
    zero_progress_streak = 0
    zero_progress_limit = max(10, len(sim.stations) * 2)
    stop_reason = "max_steps_reached"
    steps_used = 0
    for i in range(max_steps):
        steps_used = i + 1
        date_before = sim.simulation_date
        decision = strategy.decide_next_action(sim)
        progressed = _execute_decision(sim, decision)
        if not progressed:
            stop_reason = "stalled"
            break
        if sim.simulation_date == date_before:
            zero_progress_streak += 1
            if zero_progress_streak >= zero_progress_limit:
                stop_reason = "stalled_zero_progress"
                break
        else:
            zero_progress_streak = 0
        if sim.simulation_date and start_date and (sim.simulation_date - start_date).days >= max_days:
            stop_reason = "max_days_reached"
            break
    return _metrics_dict(sim, stop_reason, steps_used)


def run_full(make_strategy: Callable[[], AutoPlanStrategy], *, max_steps: int = 1500) -> Dict[str, Any]:
    """Full validation run: same stopping rule as
    scripts/compare_auto_strategies.py (runs to year_limit, 2027-12-31),
    reserved for finalist candidates -- costs much more compute than
    run_fast()."""
    config = AutoPlanConfig(**COMMON_CONFIG_KWARGS, steps=0)
    sim = _init_simulation(config)
    strategy = make_strategy()
    limit_date = datetime(COMMON_CONFIG_KWARGS["end_year"], 12, 31)
    zero_progress_streak = 0
    zero_progress_limit = max(10, len(sim.stations) * 2)
    stop_reason = "steps_limit"
    steps_used = 0
    for i in range(max_steps):
        steps_used = i + 1
        date_before = sim.simulation_date
        decision = strategy.decide_next_action(sim)
        progressed = _execute_decision(sim, decision)
        if not progressed:
            stop_reason = "stalled"
            break
        if sim.simulation_date == date_before:
            zero_progress_streak += 1
            if zero_progress_streak >= zero_progress_limit:
                stop_reason = "stalled_zero_progress"
                break
        else:
            zero_progress_streak = 0
        if sim.simulation_date and sim.simulation_date.date() > limit_date.date():
            stop_reason = "year_limit"
            break
    else:
        stop_reason = "steps_limit"
    return _metrics_dict(sim, stop_reason, steps_used)
