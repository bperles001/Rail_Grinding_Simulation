"""Adversarial/edge-case fuzzing on top of overnight_manual_route_fuzz.py --
deliberately tries to break the Manual Route engine: extreme/nonsensical
inputs, boundary values, repeated turns, huge waits, invalid tokens, bad
station pairs, very long runs. Bruno's instruction: "pode forcar muitos
cenarios, mesmo que ilogicos... e' testar falhar e erros mesmo".

Two kinds of findings are tracked separately:
  - "expected_error": the engine correctly raised/rejected bad input
    (validation working as intended -- not a bug).
  - "unexpected_exception" / "invariant_violation": a real problem.

Run standalone:
    .venv/Scripts/python.exe scripts/overnight_manual_route_adversarial.py [--scenarios N]

Findings: scripts/overnight_manual_route_adversarial_findings.jsonl
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from railroad_backend.services.auto_planner import initialize_simulation_from_args
from railroad_backend.services.manual_planner import list_available_moves
from src.models import ACTION_MOVE
from src.utils.network_loader import load_network

from overnight_manual_route_fuzz import NETWORK, SCHEDULE, TOKENS, _neighbor_pairs, _check_invariants, render_timeline_and_capture_warnings

FINDINGS_PATH = REPO_ROOT / "scripts" / "overnight_manual_route_adversarial_findings.jsonl"


def _log(f, kind: str, payload: Dict[str, Any]) -> None:
    payload = {"kind": kind, **payload}
    f.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")
    f.flush()


# ---------------------------------------------------------------------------
# Category A: boundary/invalid inputs that SHOULD raise a controlled error.
# ---------------------------------------------------------------------------

def probe_invalid_inputs(f) -> None:
    net = load_network(NETWORK)
    pairs = _neighbor_pairs(net)
    start_station, facing_station = pairs[0]

    # 1. Year boundaries.
    for bad_year in (1899, 2201, -1, 0, 10000):
        try:
            initialize_simulation_from_args(
                SCHEDULE, start_station=start_station, facing_station=facing_station,
                start_year=bad_year, end_year=bad_year + 1, second_kld=False, network_source=NETWORK,
            )
            _log(f, "unexpected_no_error", {"probe": "bad_year", "year": bad_year})
        except (ValueError, TypeError) as exc:
            _log(f, "expected_error", {"probe": "bad_year", "year": bad_year, "error": str(exc)})
        except Exception:
            _log(f, "unexpected_exception", {"probe": "bad_year", "year": bad_year, "traceback": traceback.format_exc()})

    # 2. Non-adjacent / nonsense station pairs (init_machine has a silent
    # fallback to TRO/TMI for unknown names -- confirm it actually falls
    # back sanely instead of producing a broken machine state).
    for start, facing in [("NAOEXISTE", "TAMBEMNAO"), (start_station, "NAOEXISTE"), ("ZTO", "ZTO")]:
        try:
            sim = initialize_simulation_from_args(
                SCHEDULE, start_station=start, facing_station=facing,
                start_year=2026, end_year=2027, second_kld=False, network_source=NETWORK,
            )
            ok = sim.machine is not None and sim.current_station is not None
            _log(f, "expected_error" if ok else "unexpected_exception",
                 {"probe": "bad_station_pair", "start": start, "facing": facing,
                  "fallback_station": sim.current_station.name if sim.current_station else None})
        except Exception:
            _log(f, "unexpected_exception", {"probe": "bad_station_pair", "start": start, "facing": facing, "traceback": traceback.format_exc()})

    # 3. Invalid segment_actions token / mismatched keys -- move_to() must
    # raise ValueError, not corrupt state or crash some other way.
    sim = initialize_simulation_from_args(
        SCHEDULE, start_station=start_station, facing_station=facing_station,
        start_year=2026, end_year=2027, second_kld=True, network_source=NETWORK,
    )
    options = list_available_moves(sim)
    if options:
        opt = options[0]
        segments_by_name = {s.name: s for s in sim.segments}
        segs = tuple(segments_by_name[n] for n in opt.segments)
        dest = sim.stations[opt.destination]
        steps_before = len(sim.steps)
        for bad_actions in (
            {opt.segments[0]: "tangente"},  # invalid token
            {"NOT-A-REAL-SEGMENT": "completa"},  # unknown segment name
            {},  # empty -- every segment defaults to "none", should behave like pure move
        ):
            try:
                sim.move_to(segs, dest, action=ACTION_MOVE, segment_actions=bad_actions)
                if bad_actions and "NOT-A-REAL-SEGMENT" in bad_actions or (bad_actions and list(bad_actions.values())[0] == "tangente"):
                    _log(f, "unexpected_no_error", {"probe": "bad_segment_actions", "segment_actions": bad_actions})
                else:
                    _log(f, "expected_error", {"probe": "bad_segment_actions_empty_ok", "segment_actions": bad_actions})
                    steps_before = len(sim.steps)  # this one legitimately succeeds; resync
            except ValueError as exc:
                if len(sim.steps) != steps_before:
                    _log(f, "unexpected_exception", {"probe": "bad_segment_actions_corrupted_state", "segment_actions": bad_actions, "error": str(exc)})
                else:
                    _log(f, "expected_error", {"probe": "bad_segment_actions", "segment_actions": bad_actions, "error": str(exc)})
            except Exception:
                _log(f, "unexpected_exception", {"probe": "bad_segment_actions", "segment_actions": bad_actions, "traceback": traceback.format_exc()})

    # 4. wait_days boundary values.
    for bad_days in (0, -5, 366, 10000):
        sim2 = initialize_simulation_from_args(
            SCHEDULE, start_station=start_station, facing_station=facing_station,
            start_year=2026, end_year=2027, second_kld=False, network_source=NETWORK,
        )
        try:
            sim2.wait_days(bad_days)
            if bad_days <= 0:
                _log(f, "unexpected_no_error", {"probe": "bad_wait_days", "days": bad_days})
            else:
                _log(f, "expected_error", {"probe": "large_wait_days_accepted", "days": bad_days})
        except (ValueError, TypeError) as exc:
            _log(f, "expected_error", {"probe": "bad_wait_days", "days": bad_days, "error": str(exc)})
        except Exception:
            _log(f, "unexpected_exception", {"probe": "bad_wait_days", "days": bad_days, "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Category B: extreme/degenerate random walks (long, turn-heavy, wait-heavy,
# all-completa, all-curva, rapid back-and-forth).
# ---------------------------------------------------------------------------

def run_extreme_walk(seed: int, mode: str, start_station: str, facing_station: str,
                      start_year: int, second_kld: bool, max_steps: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    scenario = {"seed": seed, "mode": mode, "start_station": start_station, "facing_station": facing_station,
                "start_year": start_year, "second_kld": second_kld, "max_steps": max_steps}
    try:
        sim = initialize_simulation_from_args(
            SCHEDULE, start_station=start_station, facing_station=facing_station,
            start_year=start_year, end_year=start_year + 2, second_kld=second_kld, network_source=NETWORK,
        )
    except Exception as exc:
        return {"scenario": scenario, "status": "skipped_init", "detail": str(exc)}

    steps_done = 0
    try:
        for _ in range(max_steps):
            if mode == "turn_spam" and sim.current_station and sim.current_station.can_turn:
                sim.flip_global_direction()
                steps_done += 1
                continue
            if mode == "wait_spam":
                sim.wait_days(rng.choice([1, 30, 90, 180, 365]))
                steps_done += 1
                continue

            options = list_available_moves(sim)
            if not options:
                if mode == "turn_spam":
                    break
                # dead end reached with no turn available -- try flipping if possible, else stop
                if sim.current_station and sim.current_station.can_turn:
                    sim.flip_global_direction()
                    steps_done += 1
                    continue
                break

            opt = rng.choice(options) if mode != "prefer_smallest" else min(options, key=lambda o: len(o.segments))
            segments_by_name = {s.name: s for s in sim.segments}
            segs = tuple(segments_by_name[n] for n in opt.segments)
            dest = sim.stations[opt.destination]

            if mode == "all_completa":
                seg_actions = {n: "completa" for n in opt.segments}
            elif mode == "all_curva":
                seg_actions = {n: "curva" for n in opt.segments}
            elif mode == "all_none":
                seg_actions = {n: "none" for n in opt.segments}
            else:
                seg_actions = {n: rng.choice(TOKENS) for n in opt.segments}

            sim.move_to(segs, dest, action=ACTION_MOVE, segment_actions=seg_actions)
            step_record = sim.steps[-1]
            problems = _check_invariants(sim, segs, seg_actions, step_record)
            if problems:
                return {"scenario": scenario, "status": "invariant_violation", "step_idx": steps_done, "problems": problems}
            steps_done += 1

        net = load_network(NETWORK)
        render_warnings = render_timeline_and_capture_warnings(sim, net)
        if render_warnings:
            return {"scenario": scenario, "status": "render_warning", "steps_done": steps_done, "warnings": render_warnings}
        return {"scenario": scenario, "status": "ok", "steps_done": steps_done}
    except Exception:
        return {"scenario": scenario, "status": "exception", "step_idx": steps_done, "traceback": traceback.format_exc()}
    finally:
        plt.close("all")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=1000)
    parser.add_argument("--seed-start", type=int, default=100000)
    args = parser.parse_args()

    net = load_network(NETWORK)
    pairs = _neighbor_pairs(net)
    rng = random.Random(999 + args.seed_start)
    modes = ["turn_spam", "wait_spam", "all_completa", "all_curva", "all_none", "prefer_smallest", "chaos"]

    results: List[Dict[str, Any]] = []
    t0 = time.time()
    with open(FINDINGS_PATH, "a", encoding="utf-8") as f:
        probe_invalid_inputs(f)

        for i in range(args.scenarios):
            seed = args.seed_start + i
            mode = modes[i % len(modes)]
            start_station, facing_station = rng.choice(pairs)
            start_year = rng.choice([2026, 2027])
            second_kld = rng.choice([True, False])
            max_steps = rng.choice([50, 150, 500, 1500])
            outcome = run_extreme_walk(seed, mode, start_station, facing_station, start_year, second_kld, max_steps)
            results.append(outcome)
            if outcome["status"] not in ("ok", "skipped_init"):
                _log(f, outcome["status"], outcome)

    elapsed = time.time() - t0
    by_status: Dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print(f"Adversarial: {len(results)} cenarios extremos em {elapsed:.1f}s")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"Findings em: {FINDINGS_PATH}")


if __name__ == "__main__":
    main()
