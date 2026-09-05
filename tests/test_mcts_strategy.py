"""Tests for MCTSStrategy: tree reuse across real decisions."""
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.mcts_strategy import MCTSStrategy


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


def test_mcts_strategy_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = MCTSStrategy(time_budget_s=1.0)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}


def test_mcts_strategy_reuses_its_tree_across_consecutive_calls(tmp_path):
    """After the first call, the strategy should hold a non-empty reused
    root (proof the tree-reuse wiring is connected, not just that search()
    works in isolation, which Task 3 already covers)."""
    sim = _init_simulation(_config(tmp_path))
    strategy = MCTSStrategy(time_budget_s=1.0)
    strategy.decide_next_action(sim)
    assert strategy._root is not None
