"""Tests for the MCTS Auto Planner strategy: cloning, opportunistic rollout
policy, tree search, and the public MCTSStrategy."""
import json
import time
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.mcts import (
    clone_simulator,
    evaluate_rollout_outcome,
    opportunistic_maintenance_action_for,
    opportunistic_needs_maintenance,
    opportunistic_rollout_decision,
    run_rollout,
)
from src.simulator import Simulator
from src.utils.network_loader import load_network


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


def test_clone_simulator_produces_an_independent_copy(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    clone = clone_simulator(sim)
    assert clone is not sim
    clone_seg = next(s for s in clone.segments if s.name == "TRO-TMI")
    real_seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    assert clone_seg is not real_seg
    clone_seg.load_curva = 999.0
    assert real_seg.load_curva != 999.0


def test_clone_simulator_shares_the_daily_map_by_reference(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    clone = clone_simulator(sim)
    assert clone.daily_map is sim.daily_map


def test_clone_simulator_is_fast_enough_for_hundreds_of_rollouts_per_second(tmp_path):
    """Regression guard for the memo-based optimization this function
    depends on: a naive `copy.deepcopy(sim)` (no memo) measured ~23
    clones/second on the real 57-segment network during planning -- far
    too slow for MCTS (needs hundreds to thousands of simulations per
    real decision within a ~10s budget). The memo-optimized version
    measured ~426 clones/second on that same network. This test uses a
    generous threshold (50/second) well below both figures, so it stays
    a real regression guard without being flaky on slower CI hardware."""
    sim = _init_simulation(_config(tmp_path))
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        clone_simulator(sim)
    elapsed = time.perf_counter() - start
    rate = iterations / elapsed
    assert rate > 50, f"expected > 50 clones/sec, got {rate:.1f}/sec -- the memo optimization may have regressed"


def test_opportunistic_needs_maintenance_true_above_proximity_ratio_even_if_not_due(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 8.0  # 0.8 ratio -- above the 0.7 proximity threshold, but not yet due (>= 10.0)
    assert opportunistic_needs_maintenance((seg,)) is True


def test_opportunistic_needs_maintenance_false_below_proximity_ratio(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 5.0  # 0.5 ratio -- below the 0.7 threshold
    assert opportunistic_needs_maintenance((seg,)) is False


def test_opportunistic_maintenance_action_prefers_full_maintain_when_tangente_near_threshold(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    seg = next(s for s in sim.segments if s.name == "TRO-TMI")
    seg.mtbt_threshold_curva = 10.0
    seg.load_curva = 3.0
    seg.mtbt_threshold_tangente = 10.0
    seg.load_tangente = 8.0
    assert opportunistic_maintenance_action_for((seg,)) == "maintain"


def _chain_network_sim(tmp_path: Path) -> Simulator:
    """A-B-C corridor with generous daily traffic so segments accumulate
    load quickly during a rollout."""
    network_path = tmp_path / "chain.json"
    network_path.write_text(
        json.dumps(
            {
                "name": "Chain",
                "stations": [
                    {"name": "A", "can_turn": False},
                    {"name": "B", "can_turn": False},
                    {"name": "C", "can_turn": False},
                ],
                "segments": [
                    {
                        "name": "A-B", "start": "A", "end": "B", "length_km": 1.0,
                        "mtbt_threshold_curva": 10.0, "mtbt_threshold_tangente": 30.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                    {
                        "name": "B-C", "start": "B", "end": "C", "length_km": 1.0,
                        "mtbt_threshold_curva": 10.0, "mtbt_threshold_tangente": 30.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01,2025-02,2025-03\nA-B,1.0,1.0,1.0\nB-C,1.0,1.0,1.0\n")
    sim = Simulator(load_network(network_path))
    from railroad_backend.domain.schedule import build_daily_map
    sim.init_machine(
        start_station_name="A", facing_station_name="B", start_year=2025,
        daily_map=build_daily_map(csv_path, 2025, 2025),
    )
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 9.0  # already past the 0.7 ratio (7.0), not yet due (10.0)
    b_c = next(s for s in sim.segments if s.name == "B-C")
    b_c.load_curva = 10.0  # already due -- forces segments_already_due(sim) True,
    # so the move toward B (crossing A-B, the only reachable segment from A)
    # happens for that reason, letting A-B's own near-threshold load be
    # picked up opportunistically along the way (the scenario this fixture
    # is designed to exercise).
    return sim


def test_opportunistic_rollout_decision_maintains_a_near_threshold_segment_while_passing(tmp_path):
    sim = _chain_network_sim(tmp_path)
    decision = opportunistic_rollout_decision(sim)
    assert decision.kind == "move"
    assert any(seg.name == "A-B" for seg in decision.segments)
    assert decision.action in {"maintain", "maintain_curves"}


def test_run_rollout_counts_opportunistic_maintenance_actions(tmp_path):
    sim = clone_simulator(_chain_network_sim(tmp_path))
    _, opportunistic_count = run_rollout(sim, max_days=10)
    assert opportunistic_count >= 1


def test_evaluate_rollout_outcome_rewards_more_opportunistic_maintenance(tmp_path):
    before = _chain_network_sim(tmp_path)
    after_more = clone_simulator(before)
    after_fewer = clone_simulator(before)
    value_more = evaluate_rollout_outcome(before, after_more, opportunistic_count=3)
    value_fewer = evaluate_rollout_outcome(before, after_fewer, opportunistic_count=0)
    assert value_more > value_fewer
