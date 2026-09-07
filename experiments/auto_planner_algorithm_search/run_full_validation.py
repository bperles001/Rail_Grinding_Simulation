"""Full year_limit validation of the leading candidate found overnight
(rd45, pr0.85, ec1.41) at a realistic (not search-cheap) time budget,
for a direct apples-to-apples comparison against the Task 6 study's
reference rows (docs/2026-08-11-auto-planner-algorithm-study.md)."""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import REFERENCE_METRICS, run_full  # noqa: E402
from railroad_backend.services.auto_planner_strategies.mcts_strategy import MCTSStrategy  # noqa: E402

CONFIGS = {
    "mcts_tuned_full_validation": dict(time_budget_s=3.0, rollout_max_days=45, proximity_ratio=0.85, exploration_constant=1.41),
    "mcts_control_no_opportunism_full_validation": dict(time_budget_s=3.0, rollout_max_days=45, proximity_ratio=1.0, exploration_constant=1.41),
}

results = {}
for name, params in CONFIGS.items():
    print(f"running {name} to year_limit ...", flush=True)
    start = time.monotonic()
    metrics = run_full(lambda _p=params: MCTSStrategy(**_p))
    elapsed = time.monotonic() - start
    results[name] = {"params": params, "metrics": metrics, "elapsed_s": round(elapsed, 1)}
    print(f"  -> {metrics} ({elapsed:.1f}s)", flush=True)
    (HERE / "full_validation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

print("\nFor comparison, Task 6 reference metrics (all run to year_limit already):")
for name, m in REFERENCE_METRICS.items():
    print(f"  {name}: {m}")

print("\nDone. Results saved to full_validation_results.json")
