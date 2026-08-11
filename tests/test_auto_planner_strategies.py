"""Tests for the pluggable Auto Planner strategy interface."""
import pytest

from railroad_backend.services.auto_planner_strategies.base import AutoPlanStrategy, StepDecision


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
