"""Study script: run Greedy / Rolling-horizon ILP (with commitment) /
Simulated Annealing against the real network across several planning
horizons, and write a markdown report for human review. Not part of the
pytest suite -- run manually:
.venv\\Scripts\\python.exe scripts\\compare_auto_strategies.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from railroad_backend.services.auto_planner import run_auto_plan_from_args  # noqa: E402
from railroad_backend.services.manual_planner import ManualPlanConfig, replay_manual_plan  # noqa: E402

NETWORK_FILE = Path(__file__).resolve().parent.parent / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE_CSV = Path(__file__).resolve().parent.parent / "data" / "mtbt_schedule.csv"
SAVED_PLANS_FILE = Path(__file__).resolve().parent.parent / "data" / "saved_plans.json"
REPORT_FILE = Path(__file__).resolve().parent.parent / "docs" / "2026-08-11-auto-planner-algorithm-study.md"

WINDOW_DAYS = [60, 90, 120, 180]
SA_SEEDS = [1, 2, 3]
STEPS = 400
COMMON_KWARGS = dict(
    csv_path=SCHEDULE_CSV,
    start_station="ZTO",
    facing_station="ZCZ",
    start_year=2026,
    end_year=2027,
    steps=STEPS,
    second_kld=True,
    network_source=NETWORK_FILE,
)


def _metrics(result) -> Dict[str, Any]:
    sim = result.simulator
    idle = getattr(sim, "idle_days_total", 0)
    total = sim.movement_days_total + sim.maintenance_days_total + idle
    over_threshold = 0
    for seg in sim.segments:
        if seg.mtbt_threshold_curva and seg.load_curva >= seg.mtbt_threshold_curva:
            over_threshold += 1
        if seg.mtbt_threshold_tangente and seg.load_tangente >= seg.mtbt_threshold_tangente:
            over_threshold += 1
    return {
        "stop_reason": result.stop_reason,
        "steps": len(sim.steps),
        "maintenance_count": sim.maintenance_count,
        "movement_days": sim.movement_days_total,
        "maintenance_days": sim.maintenance_days_total,
        "idle_days": idle,
        "total_days": total,
        "segments_over_threshold_at_end": over_threshold,
    }


def _run_greedy() -> Dict[str, Any]:
    result = run_auto_plan_from_args(**COMMON_KWARGS, strategy="greedy")
    return _metrics(result)


def _run_ilp(window_days: int) -> Dict[str, Any]:
    result = run_auto_plan_from_args(
        **COMMON_KWARGS, strategy="rolling_ilp",
        ilp_window_days=window_days, ilp_weight_coverage=10.0, ilp_weight_travel=1.0,
        ilp_weight_proximity=0.5, ilp_time_limit_s=5.0,
    )
    return _metrics(result)


def _run_sa(window_days: int, seed: int) -> Dict[str, Any]:
    result = run_auto_plan_from_args(
        **COMMON_KWARGS, strategy="simulated_annealing",
        sa_window_days=window_days, sa_weight_coverage=10.0, sa_weight_travel=1.0,
        sa_weight_proximity=0.5, sa_iterations=2000, sa_seed=seed,
    )
    return _metrics(result)


def _run_mcts() -> Dict[str, Any]:
    result = run_auto_plan_from_args(**COMMON_KWARGS, strategy="mcts")
    return _metrics(result)


class _ManualResultAdapter:
    """Adapts a ManualPlanReplay (.simulator, .errors) to the small
    (.simulator, .stop_reason) shape _metrics() expects, so the manual
    reference row can reuse it unchanged."""

    def __init__(self, replay) -> None:
        self.simulator = replay.simulator
        self.stop_reason = "manual_plan_end" if not replay.errors else f"errors:{len(replay.errors)}"


def _replay_manual_plan() -> Dict[str, Any]:
    data = json.loads(SAVED_PLANS_FILE.read_text(encoding="utf-8"))
    entry = data["manual"]["Plano - Nos (v2 segment_actions)"]
    cfg = entry["config"]
    config = ManualPlanConfig(
        csv_path=SCHEDULE_CSV,
        start_station=cfg["start_station"],
        facing_station=cfg["facing_station"],
        start_year=cfg["start_year"],
        end_year=cfg["end_year"],
        second_kld=cfg["second_kld"],
        network_source=NETWORK_FILE,
    )
    replay = replay_manual_plan(config, entry["steps"])
    if replay.errors:
        print(f"WARNING: manual plan replay had {len(replay.errors)} error(s): {replay.errors[:3]}")
    return _metrics(_ManualResultAdapter(replay))


def _format_row(label: str, m: Dict[str, Any]) -> str:
    return (
        f"| {label} | {m['stop_reason']} | {m['steps']} | {m['maintenance_count']} | "
        f"{m['movement_days']} | {m['maintenance_days']} | {m['idle_days']} | {m['total_days']} | "
        f"{m['segments_over_threshold_at_end']} |"
    )


def main() -> None:
    lines: List[str] = [
        "# Auto Planner algorithm study — Greedy vs Rolling-horizon ILP vs Simulated Annealing vs MCTS vs real manual plan",
        "",
        f"Real network: `{NETWORK_FILE.name}`, ZTO→ZCZ, 2026–2027, 2º KLD, {STEPS} steps (manual reference row runs its own fixed 88-step plan).",
        "",
        "## Summary table",
        "",
        "| Strategy | stop_reason | steps | maint. actions | movement days | maint. days | idle days | total days | segments over threshold |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    print("Replaying real manual plan (reference row)...")
    manual_metrics = _replay_manual_plan()
    lines.append(_format_row("**Manual plan (real, replayed)**", manual_metrics))

    print("Running greedy...")
    greedy_metrics = _run_greedy()
    lines.append(_format_row("Greedy", greedy_metrics))

    print("Running mcts...")
    mcts_metrics = _run_mcts()
    lines.append(_format_row("MCTS (opportunistic grouping)", mcts_metrics))

    for window in WINDOW_DAYS:
        print(f"Running rolling_ilp (window={window})...")
        ilp_metrics = _run_ilp(window)
        lines.append(_format_row(f"Rolling ILP (window={window}d)", ilp_metrics))

        sa_results = []
        for seed in SA_SEEDS:
            print(f"Running simulated_annealing (window={window}, seed={seed})...")
            sa_results.append(_run_sa(window, seed))
        for seed, m in zip(SA_SEEDS, sa_results):
            lines.append(_format_row(f"Simulated Annealing (window={window}d, seed={seed})", m))
        totals = [m["total_days"] for m in sa_results]
        maint = [m["maintenance_count"] for m in sa_results]
        lines.append(
            f"| Simulated Annealing (window={window}d) min/avg/max | - | - | "
            f"{min(maint)}/{sum(maint) / len(maint):.1f}/{max(maint)} | - | - | - | "
            f"{min(totals)}/{sum(totals) / len(totals):.1f}/{max(totals)} | - |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Greedy has no planning window (1-hop lookahead), listed once for reference against every ILP/SA row."
    )
    lines.append(
        "- Simulated Annealing is stochastic: 3 seeds per window are run and reported individually plus a min/avg/max summary row."
    )
    lines.append(
        "- `segments_over_threshold_at_end` counts curva+tangente components still over their MTBT threshold when the run stops -- lower is better coverage."
    )
    lines.append(
        "- The manual plan row replays Bruno's real 88-step in-app plan (`data/saved_plans.json`, \"Plano - Nos (v2 segment_actions)\") against the same real network -- this is the reference the MCTS strategy was built to close the gap against (measured 81-93% time-on-maintenance for the human vs. 65-71% for Greedy/ILP/SA before MCTS)."
    )
    lines.append(
        "- MCTS runs a single row (no planning-window parameter to sweep, unlike ILP/SA) at its internal 10s-per-decision default budget."
    )

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
