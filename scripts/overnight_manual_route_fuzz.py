"""Exploratory fuzz-testing of the Manual Route engine against the real
network (network_20251223_115340.json), looking for crashes/invariant
violations across a wide combinatorial scenario space before the manual
stage is declared done and work moves to the Auto Planner.

Not a pytest suite -- this is a QA/exploration tool, run standalone:

    .venv/Scripts/python.exe scripts/overnight_manual_route_fuzz.py [--scenarios N] [--seed-start N]

Appends findings to scripts/overnight_manual_route_fuzz_findings.jsonl and
prints a summary at the end. Safe to re-run repeatedly (only reads the
network; never mutates data/networks/*.json or data/saved_plans.json).
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from railroad_backend.services.auto_planner import initialize_simulation_from_args
from railroad_backend.services.manual_planner import list_available_moves
from src.models import ACTION_MOVE
from src.simulator import Simulator, prepare_timeline_rows
from src.utils.network_loader import load_network
from src.utils.timeline_generator import TimelineGenerator

NETWORK = REPO_ROOT / "data" / "networks" / "network_20251223_115340.json"
SCHEDULE = REPO_ROOT / "data" / "mtbt_schedule.csv"
FINDINGS_PATH = REPO_ROOT / "scripts" / "overnight_manual_route_fuzz_findings.jsonl"

TOKENS = ["none", "curva", "completa"]


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def render_timeline_and_capture_warnings(sim: Simulator, net) -> List[str]:
    """Run the exact same rendering pipeline the UI uses and return any
    warning messages raised -- both real `warnings.warn()` calls AND
    matplotlib's own logger.warning() calls (e.g. the Locator MAXTICKS
    message for absurdly long time spans uses `_log.warning(...)`, NOT
    `warnings.warn`, so a plain warnings.catch_warnings() misses it
    silently -- confirmed by reproducing it and seeing zero warnings
    captured until this logging handler was added). Neither of these
    ever raises an exception, so a plain try/except would miss them too."""
    mpl_logger = logging.getLogger("matplotlib")
    handler = _LogCapture()
    mpl_logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rows, y_order, _alias = prepare_timeline_rows(sim.steps, segments=sim.segments, timeline_order=net.timeline_order)
            gen = TimelineGenerator(rows, y_order=y_order)
            gen.process_data()
            gen.create_timeline_plot()
    finally:
        mpl_logger.removeHandler(handler)
    return [str(w.message) for w in caught] + handler.records


def _neighbor_pairs(net) -> List[tuple]:
    """Every (start_station, facing_station) pair connected by a real
    segment -- valid init_machine() inputs."""
    pairs = []
    seen = set()
    for seg in net.segments:
        for a, b in ((seg.start_station.name, seg.end_station.name), (seg.end_station.name, seg.start_station.name)):
            if (a, b) not in seen:
                seen.add((a, b))
                pairs.append((a, b))
    return pairs


def _random_segment_actions(rng: random.Random, segment_names: tuple) -> Dict[str, str]:
    tokens = {name: rng.choice(TOKENS) for name in segment_names}
    # Bias away from "all none" (a pure move) about half the time, so
    # maintenance-heavy paths get exercised too -- otherwise random choice
    # among 3 tokens^N segments skews towards "at least one non-none"
    # already for N>=2, this mostly matters for single-segment moves.
    if all(v == "none" for v in tokens.values()) and rng.random() < 0.5:
        pick = rng.choice(segment_names)
        tokens[pick] = rng.choice(["curva", "completa"])
    return tokens


def _check_invariants(sim: Simulator, segments_used: tuple, segment_actions: Dict[str, str], step: Dict[str, Any]) -> List[str]:
    """Note: a "curva"/"completa" reset zeroes the accumulator INSIDE
    move_to(), but the same step's own duration then re-accrues real
    traffic on top via _apply_daily_mtbt_for_period() -- intentional
    domain behavior (mtbt_after_curva/tangente, confirmed 2026-08-10). So
    "load == 0 right after a reset token" is NOT a valid invariant here;
    only structural/label consistency is checked."""
    problems = []
    seg_by_name = {s.name: s for s in sim.segments}
    for name, token in segment_actions.items():
        seg = seg_by_name.get(name)
        if seg is None:
            continue
        if seg.load_curva < 0 or seg.load_tangente < 0:
            problems.append(f"segment {name} has negative load after step (curva={seg.load_curva}, tangente={seg.load_tangente})")

    maintained = set(step.get("maintained_segments") or [])
    expected_maintained = {name for name, token in segment_actions.items() if token != "none"}
    if maintained != expected_maintained:
        problems.append(f"maintained_segments {sorted(maintained)} != expected {sorted(expected_maintained)}")

    had_completa = any(t == "completa" for t in segment_actions.values())
    had_curva = any(t == "curva" for t in segment_actions.values())
    expected_action = "maintenance" if had_completa else "maintenance_curves" if had_curva else "move"
    if step.get("action") != expected_action:
        problems.append(f"step action={step.get('action')!r} but expected {expected_action!r} for segment_actions={segment_actions}")

    kld_reading = step.get("kld_reading") or {}
    if set(kld_reading.keys()) != expected_maintained:
        problems.append(f"kld_reading keys {sorted(kld_reading.keys())} != maintained segments {sorted(expected_maintained)}")
    if sim.machine and sim.machine.second_kld_installed and expected_maintained:
        if not all(kld_reading.values()):
            problems.append(f"second_kld_installed=True but kld_reading has a False entry: {kld_reading}")

    return problems


def run_scenario(
    seed: int,
    start_station: str,
    facing_station: str,
    start_year: int,
    second_kld: bool,
    allow_turns: bool,
    max_steps: int,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    scenario = {
        "seed": seed,
        "start_station": start_station,
        "facing_station": facing_station,
        "start_year": start_year,
        "second_kld": second_kld,
        "allow_turns": allow_turns,
        "max_steps": max_steps,
    }
    log: List[Dict[str, Any]] = []
    try:
        sim = initialize_simulation_from_args(
            SCHEDULE,
            start_station=start_station,
            facing_station=facing_station,
            start_year=start_year,
            end_year=start_year + 1,
            second_kld=second_kld,
            network_source=NETWORK,
        )
    except Exception as exc:  # invalid station pair etc -- not a bug, just skip
        return {"scenario": scenario, "status": "skipped_init", "detail": str(exc)}

    steps_done = 0
    try:
        for _ in range(max_steps):
            did_turn = False
            if allow_turns and sim.current_station and sim.current_station.can_turn and rng.random() < 0.15:
                sim.flip_global_direction()
                did_turn = True
                log.append({"kind": "turn"})
            elif rng.random() < 0.1:
                wait_days = rng.randint(1, 30)
                sim.wait_days(wait_days)
                log.append({"kind": "wait", "days": wait_days})
            else:
                options = list_available_moves(sim)
                if not options:
                    break
                opt = rng.choice(options)
                segments_by_name = {s.name: s for s in sim.segments}
                segs = tuple(segments_by_name[n] for n in opt.segments)
                dest = sim.stations[opt.destination]
                seg_actions = _random_segment_actions(rng, opt.segments)
                result_step = sim.move_to(segs, dest, action=ACTION_MOVE, segment_actions=seg_actions)
                step_record = sim.steps[-1]
                log.append({"kind": "move", "segments": opt.segments, "destination": opt.destination, "segment_actions": seg_actions})
                problems = _check_invariants(sim, segs, seg_actions, step_record)
                if problems:
                    return {
                        "scenario": scenario, "status": "invariant_violation",
                        "step_idx": steps_done, "problems": problems, "log_tail": log[-5:],
                    }
            steps_done += 1

        # Exercise the timeline pipeline against whatever real state this
        # random walk produced -- same code path the UI uses to render.
        net = load_network(NETWORK)
        render_warnings = render_timeline_and_capture_warnings(sim, net)
        if render_warnings:
            return {"scenario": scenario, "status": "render_warning", "steps_done": steps_done, "warnings": render_warnings}

        return {"scenario": scenario, "status": "ok", "steps_done": steps_done}
    except Exception:
        return {
            "scenario": scenario, "status": "exception",
            "step_idx": steps_done, "traceback": traceback.format_exc(),
            "log_tail": log[-5:],
        }
    finally:
        plt.close("all")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=400)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=100)
    args = parser.parse_args()

    net = load_network(NETWORK)
    pairs = _neighbor_pairs(net)
    rng = random.Random(12345 + args.seed_start)

    results: List[Dict[str, Any]] = []
    t0 = time.time()
    with open(FINDINGS_PATH, "a", encoding="utf-8") as f:
        for i in range(args.scenarios):
            seed = args.seed_start + i
            start_station, facing_station = rng.choice(pairs)
            start_year = rng.choice([2026, 2027])
            second_kld = rng.choice([True, False])
            allow_turns = rng.choice([True, False])
            # Vary run length -- short walks and long multi-year-spanning
            # walks exercise different edge cases (e.g. dates rolling past
            # the CSV schedule's covered range on very long runs).
            max_steps = rng.choice([20, 40, args.max_steps, args.max_steps * 3])
            outcome = run_scenario(seed, start_station, facing_station, start_year, second_kld, allow_turns, max_steps)
            results.append(outcome)
            if outcome["status"] != "ok" and outcome["status"] != "skipped_init":
                f.write(json.dumps(outcome, default=str, ensure_ascii=False) + "\n")
                f.flush()

    elapsed = time.time() - t0
    by_status: Dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    print(f"Rodou {len(results)} cenarios em {elapsed:.1f}s")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"Findings (nao-ok, nao-skip) gravados em: {FINDINGS_PATH}")


if __name__ == "__main__":
    main()
