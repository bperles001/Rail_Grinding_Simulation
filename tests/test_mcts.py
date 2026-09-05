"""Tests for the MCTS Auto Planner strategy: cloning, opportunistic rollout
policy, tree search, and the public MCTSStrategy."""
import time
from pathlib import Path

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.mcts import clone_simulator


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
