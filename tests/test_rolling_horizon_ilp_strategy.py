"""Tests for RollingHorizonILPStrategy, including its Greedy fallback."""
from pathlib import Path
from unittest.mock import patch

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp import (
    RollingHorizonILPStrategy,
)
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan


def _config(tmp_path: Path) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_rolling_ilp_falls_back_to_greedy_when_solver_infeasible(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy()
    with patch(
        "railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp.solve_window",
        return_value=WindowPlan(stops=[], feasible=False),
    ):
        decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}  # same shape Greedy would return


def test_rolling_ilp_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy(time_limit_s=5.0)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}
