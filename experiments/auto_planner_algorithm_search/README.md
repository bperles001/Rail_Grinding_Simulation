# Auto Planner algorithm search (experimental, isolated)

Overnight open-ended search (2026-09-06) for a better Auto Planner
automatic-simulation algorithm than the ones shipped in `STRATEGY_REGISTRY`
(`greedy`, `rolling_ilp`, `simulated_annealing`, `mcts`). Bruno's explicit
instruction: try as many approaches as useful ("pode viajar, inventar varias
formas"), but **never modify the shipped program** — nothing here is
imported by `src/`, nothing changes `STRATEGY_REGISTRY`, and no file under
`src/` is edited as part of this search. Every candidate here either
instantiates the real `MCTSStrategy`/`GreedyUrgencyStrategy`/etc. with
different constructor arguments (already-exposed, safe), or is a
standalone new class living entirely in this directory.

## Why a separate harness

The production comparison script (`scripts/compare_auto_strategies.py`,
Task 6 of `docs/superpowers/plans/2026-09-05-mcts-opportunistic-strategy.md`)
runs every strategy for a fixed **step count** (400). That run showed MCTS
stopping at `steps_limit` (701 simulated days covered) while every other
strategy ran to `year_limit` (~730 days) -- an unfair comparison, since
MCTS simply had less simulated calendar time to accumulate maintenance
days. `harness.py` here fixes this: candidates are compared by **simulated
calendar days**, not step count.

## Files

- `harness.py` -- shared real-network setup, a fast proxy-metric runner
  (fixed calendar-day horizon, for cheap broad search) and a full
  year_limit runner (for finalist validation), plus the manual-plan and
  Greedy/ILP/SA reference metrics carried over from the Task 6 study.
- `candidates.py` -- candidate strategy definitions, added incrementally
  across the night as ideas are tried.
- `run_batch.py` -- runs a named subset of candidates through the fast
  harness and appends results to `results.jsonl` (append-only, safe
  against interruption) and regenerates `ranking.md`.
- `results.jsonl` -- one JSON object per candidate run (accumulates all
  night).
- `ranking.md` -- human-readable, regenerated after every batch, sorted
  best-first by the target metric (% simulated time spent in real
  maintenance -- the metric the whole MCTS effort was built to move).
