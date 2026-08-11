"""Tests for the pluggable Auto Planner strategy interface."""
from datetime import datetime
from pathlib import Path

import pytest

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.base import AutoPlanStrategy, StepDecision
from railroad_backend.services.auto_planner_strategies.greedy import GreedyUrgencyStrategy


def test_step_decision_move_holds_required_fields():
    decision = StepDecision(kind="move", segments=("seg-placeholder",), next_station="station-placeholder", action="maintain")
    assert decision.kind == "move"
    assert decision.action == "maintain"


def test_step_decision_wait_holds_days():
    decision = StepDecision(kind="wait", wait_days=5)
    assert decision.kind == "wait"
    assert decision.wait_days == 5


def test_auto_plan_strategy_is_abstract():
    with pytest.raises(TypeError):
        AutoPlanStrategy()  # abstract method not implemented


def _small_config(tmp_path: Path) -> AutoPlanConfig:
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


def test_greedy_strategy_returns_a_decision(tmp_path):
    sim = _init_simulation(_small_config(tmp_path))
    strategy = GreedyUrgencyStrategy()
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}


def test_greedy_strategy_prioritizes_due_segment_over_moving(tmp_path):
    sim = _init_simulation(_small_config(tmp_path))
    # Force the segment leaving the start station to already be due.
    due_segment = next(s for s in sim.segments if s.name == "TRO-TMI")
    due_segment.mtbt_threshold_curva = 1.0
    due_segment.load_curva = 5.0
    due_segment.mtbt_threshold_tangente = 1.0
    due_segment.load_tangente = 5.0
    strategy = GreedyUrgencyStrategy()
    decision = strategy.decide_next_action(sim)
    assert decision.kind == "move"
    assert decision.action in {"maintain", "maintain_curves"}
