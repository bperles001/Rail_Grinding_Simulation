# Auto Planner algorithm search -- overnight ranking

Sorted by `segments_over_threshold_at_end` ascending (fewer is
better -- the real, ungameable measure of network health at a fixed
calendar-day horizon), with `pct_maintenance` as a secondary
efficiency stat. See the note in run_batch.py for why
`pct_maintenance` alone is NOT used as the primary ranking key.

## Fixed reference points (from the Task 6 study, not recomputed here)

| Reference | pct_maintenance | segments_over_threshold_at_end | total_days | note |
|---|---|---|---|---|
| manual_plan_real | 92.8% | 25 | 359 | 88-step real plan, own horizon (not 2026-2027 full range) |
| greedy | 14.1% | 92 | 731 |  |
| rolling_ilp_best(window=90d) | 56.0% | 41 | 730 |  |
| simulated_annealing_best(window=90d,seed=2) | 75.1% | 21 | 730 |  |
| mcts_default_UNFAIR_stepcapped | 58.9% | 26 | 701 | stopped at steps_limit (400), NOT year_limit -- not directly comparable, see module docstring |

## Candidate results (this search)

| Rank | id | category | pct_maintenance | segments_over_threshold | movement_days | maintenance_days | steps_used | stop_reason | params |
|---|---|---|---|---|---|---|---|---|---|
| 1 | mcts_grid_rd45_pr0.85_ec0.7 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 2 | mcts_grid_rd45_pr0.85_ec1.41 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 3 | mcts_grid_rd45_pr0.85_ec2.5 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 4 | mcts_grid_rd20_pr0.7_ec0.7 | mcts_hyperparam_grid | 59.1% | 33 | 74 | 107 | 104 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 5 | mcts_grid_rd20_pr0.7_ec2.5 | mcts_hyperparam_grid | 59.1% | 33 | 74 | 107 | 104 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 6 | mcts_grid_rd20_pr0.7_ec1.41 | mcts_hyperparam_grid | 56.3% | 34 | 80 | 103 | 109 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 7 | mcts_grid_rd20_pr0.85_ec1.41 | mcts_hyperparam_grid | 44.4% | 40 | 100 | 80 | 116 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 8 | mcts_grid_rd20_pr0.85_ec2.5 | mcts_hyperparam_grid | 44.4% | 40 | 100 | 80 | 118 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 9 | mcts_grid_rd45_pr0.7_ec0.7 | mcts_hyperparam_grid | 40.7% | 40 | 108 | 74 | 121 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 10 | mcts_grid_rd45_pr0.7_ec2.5 | mcts_hyperparam_grid | 40.7% | 40 | 108 | 74 | 125 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 11 | mcts_grid_rd45_pr0.7_ec1.41 | mcts_hyperparam_grid | 40.7% | 41 | 108 | 74 | 127 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 12 | mcts_grid_rd20_pr0.85_ec0.7 | mcts_hyperparam_grid | 42.5% | 42 | 104 | 77 | 119 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 13 | mcts_grid_rd45_pr0.5_ec0.7 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 14 | mcts_grid_rd45_pr0.5_ec1.41 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 15 | mcts_grid_rd45_pr0.5_ec2.5 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 16 | mcts_grid_rd20_pr0.5_ec0.7 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 17 | mcts_grid_rd20_pr0.5_ec1.41 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 18 | mcts_grid_rd20_pr0.5_ec2.5 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 19 | heuristic_maximal_opportunistic | structural_heuristic | 99.4% | 54 | 1 | 180 | 47 | max_days_reached | `{}` |
| 20 | baseline_greedy | baseline | 27.9% | 57 | 132 | 51 | 81 | max_days_reached | `{}` |
| 21 | mcts_grid_rd90_pr0.7_ec0.7 | mcts_hyperparam_grid | 11.1% | 63 | 160 | 20 | 162 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 22 | mcts_grid_rd90_pr0.5_ec0.7 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 23 | mcts_grid_rd90_pr0.5_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 24 | mcts_grid_rd90_pr0.5_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 25 | mcts_grid_rd90_pr0.7_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 26 | mcts_grid_rd90_pr0.7_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 27 | mcts_grid_rd90_pr0.85_ec0.7 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 28 | mcts_grid_rd90_pr0.85_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 29 | mcts_grid_rd90_pr0.85_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 30 | heuristic_corridor_sweep_pr0.5 | structural_heuristic | 28.3% | 67 | 129 | 51 | 49 | max_days_reached | `{"proximity_ratio": 0.5}` |
| 31 | heuristic_corridor_sweep_pr0.7 | structural_heuristic | 19.2% | 67 | 147 | 35 | 53 | max_days_reached | `{"proximity_ratio": 0.7}` |