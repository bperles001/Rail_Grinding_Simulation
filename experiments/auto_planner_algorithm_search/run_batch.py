"""Run a named batch of candidates through the fast (calendar-day-bounded)
harness, append each result to results.jsonl as it completes (safe against
interruption), then regenerate ranking.md sorted by pct_maintenance.

Usage: .venv\\Scripts\\python.exe experiments\\auto_planner_algorithm_search\\run_batch.py batch1
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from candidates import BATCHES  # noqa: E402
from harness import REFERENCE_METRICS, run_fast  # noqa: E402

RESULTS_FILE = HERE / "results.jsonl"
RANKING_FILE = HERE / "ranking.md"


def _load_all_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    rows = []
    for line in RESULTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_ranking(rows: list[dict]) -> None:
    ok_rows = [r for r in rows if r.get("ok")]
    # PRIMARY key: segments_over_threshold_at_end (ascending -- fewer is
    # better), at the SAME fixed calendar-day horizon for every candidate.
    # `pct_maintenance` was the original target metric but is gameable: the
    # smoke-test candidate "heuristic_maximal_opportunistic" hit 99.4%
    # pct_maintenance by maintaining every segment it touched regardless of
    # need, barely moving (1 day of movement in 47 steps) and ending with
    # 54 segments still over threshold -- worse network health than
    # Greedy's 57, despite the highest pct_maintenance of any candidate
    # tried. segments_over_threshold_at_end cannot be gamed the same way
    # once the horizon is fixed equally for every candidate (see
    # harness.py), so it is the real, ungameable measure of "is the
    # network actually in better shape after the same amount of time" --
    # pct_maintenance is kept as a secondary efficiency stat only.
    ok_rows.sort(key=lambda r: (r["metrics"]["segments_over_threshold_at_end"], -r["metrics"]["pct_maintenance"]))
    lines = [
        "# Auto Planner algorithm search -- overnight ranking",
        "",
        "Sorted by `segments_over_threshold_at_end` ascending (fewer is",
        "better -- the real, ungameable measure of network health at a fixed",
        "calendar-day horizon), with `pct_maintenance` as a secondary",
        "efficiency stat. See the note in run_batch.py for why",
        "`pct_maintenance` alone is NOT used as the primary ranking key.",
        "",
        "## Fixed reference points (from the Task 6 study, not recomputed here)",
        "",
        "| Reference | pct_maintenance | segments_over_threshold_at_end | total_days | note |",
        "|---|---|---|---|---|",
    ]
    for name, m in REFERENCE_METRICS.items():
        lines.append(
            f"| {name} | {m['pct_maintenance']:.1%} | {m['segments_over_threshold_at_end']} | {m['total_days']} | {m.get('note', '')} |"
        )
    lines += [
        "",
        "## Candidate results (this search)",
        "",
        "| Rank | id | category | pct_maintenance | segments_over_threshold | movement_days | maintenance_days | steps_used | stop_reason | params |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, r in enumerate(ok_rows, start=1):
        m = r["metrics"]
        lines.append(
            f"| {rank} | {r['id']} | {r['category']} | {m['pct_maintenance']:.1%} | "
            f"{m['segments_over_threshold_at_end']} | {m['movement_days']} | {m['maintenance_days']} | "
            f"{m['steps_used']} | {m['stop_reason']} | `{json.dumps(r['params'])}` |"
        )

    failed = [r for r in rows if not r.get("ok")]
    if failed:
        lines += ["", "## Failed candidates", ""]
        for r in failed:
            lines.append(f"- `{r['id']}`: {r['error']}")

    RANKING_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in BATCHES:
        print(f"Usage: run_batch.py <{'|'.join(BATCHES)}>")
        sys.exit(1)
    batch_name = sys.argv[1]
    candidates = BATCHES[batch_name]

    for candidate in candidates:
        cid = candidate["id"]
        print(f"[{batch_name}] running {cid} ...", flush=True)
        start = time.monotonic()
        row: dict
        try:
            metrics = run_fast(candidate["make_strategy"], max_days=180, max_steps=250)
            elapsed = time.monotonic() - start
            row = {
                "ok": True,
                "batch": batch_name,
                "id": cid,
                "category": candidate["category"],
                "params": candidate["params"],
                "metrics": metrics,
                "elapsed_s": round(elapsed, 1),
            }
            print(f"  -> pct_maintenance={metrics['pct_maintenance']:.1%} segments_over={metrics['segments_over_threshold_at_end']} ({elapsed:.1f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001 -- overnight batch must not die on one bad candidate
            elapsed = time.monotonic() - start
            row = {
                "ok": False,
                "batch": batch_name,
                "id": cid,
                "category": candidate["category"],
                "params": candidate["params"],
                "error": f"{exc}\n{traceback.format_exc()}",
                "elapsed_s": round(elapsed, 1),
            }
            print(f"  -> FAILED: {exc}", flush=True)

        with RESULTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

        _write_ranking(_load_all_results())

    print(f"[{batch_name}] done. Ranking written to {RANKING_FILE}")


if __name__ == "__main__":
    main()
