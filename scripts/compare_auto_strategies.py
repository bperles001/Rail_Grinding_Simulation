"""One-off script: run Greedy and Rolling-horizon ILP against the real network
and print a side-by-side metrics comparison. Not part of the pytest suite —
run manually: .venv\\Scripts\\python.exe scripts\\compare_auto_strategies.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from railroad_backend.services.auto_planner import run_auto_plan_from_args  # noqa: E402

NETWORK_FILE = Path(__file__).resolve().parent.parent / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE_CSV = Path(__file__).resolve().parent.parent / "data" / "mtbt_schedule.csv"


def _run(strategy: str):
    kwargs = dict(
        csv_path=SCHEDULE_CSV,
        start_station="ZTO",
        facing_station="ZCZ",
        start_year=2026,
        end_year=2027,
        steps=400,
        second_kld=True,
        network_source=NETWORK_FILE,
        strategy=strategy,
    )
    if strategy == "rolling_ilp":
        kwargs.update(ilp_window_days=60, ilp_weight_coverage=10.0, ilp_weight_travel=1.0, ilp_weight_proximity=0.5, ilp_time_limit_s=5.0)
    return run_auto_plan_from_args(**kwargs)


def main() -> None:
    for strategy in ("greedy", "rolling_ilp"):
        result = _run(strategy)
        sim = result.simulator
        idle = getattr(sim, "idle_days_total", 0)
        total = sim.movement_days_total + sim.maintenance_days_total + idle
        print(f"--- {strategy} ---")
        print(f"stop_reason={result.stop_reason} steps={len(sim.steps)} maintenance_count={sim.maintenance_count}")
        print(f"movement_days={sim.movement_days_total} maintenance_days={sim.maintenance_days_total} idle_days={idle} total_days={total}")


if __name__ == "__main__":
    main()
