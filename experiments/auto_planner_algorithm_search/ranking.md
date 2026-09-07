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
| 1 | mcts_refine_rd45_pr0.85 | mcts_refined_grid | 69.4% | 12 | 55 | 125 | 78 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 2 | variance_leader_rd45_pr0.85_trial1 | variance_check | 69.4% | 12 | 55 | 125 | 78 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 3 | variance_leader_rd45_pr0.85_trial3 | variance_check | 69.4% | 12 | 55 | 125 | 82 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 4 | variance_leader_rd45_pr0.85_trial2 | variance_check | 68.7% | 12 | 57 | 125 | 84 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 5 | mcts_grid_rd45_pr0.85_ec0.7 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 6 | mcts_grid_rd45_pr0.85_ec1.41 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 7 | mcts_grid_rd45_pr0.85_ec2.5 | mcts_hyperparam_grid | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 8 | mcts_budget_robustness_tb5.0 | mcts_budget_robustness | 67.2% | 14 | 59 | 121 | 85 | max_days_reached | `{"time_budget_s": 5.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 9 | variance_control_rd45_pr1.0_trial2 | variance_check | 67.2% | 14 | 59 | 121 | 83 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 1.0, "exploration_constant": 1.41}` |
| 10 | variance_control_rd45_pr1.0_trial3 | variance_check | 67.2% | 14 | 59 | 121 | 83 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 1.0, "exploration_constant": 1.41}` |
| 11 | mcts_control_no_opportunism_rd45_pr1.0 | mcts_control | 65.0% | 16 | 63 | 117 | 86 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 1.0, "exploration_constant": 1.41}` |
| 12 | mcts_winner_horizon365 | mcts_horizon_robustness | 66.1% | 21 | 124 | 242 | 180 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 13 | mcts_refine_rd30_pr0.95 | mcts_refined_grid | 72.2% | 25 | 50 | 130 | 82 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 30, "proximity_ratio": 0.95, "exploration_constant": 1.41}` |
| 14 | mcts_budget_robustness_tb10.0 | mcts_budget_robustness | 56.4% | 31 | 79 | 102 | 98 | max_days_reached | `{"time_budget_s": 10.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 15 | variance_control_rd45_pr1.0_trial1 | variance_check | 54.4% | 31 | 82 | 98 | 100 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 1.0, "exploration_constant": 1.41}` |
| 16 | mcts_grid_rd20_pr0.7_ec0.7 | mcts_hyperparam_grid | 59.1% | 33 | 74 | 107 | 104 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 17 | mcts_grid_rd20_pr0.7_ec2.5 | mcts_hyperparam_grid | 59.1% | 33 | 74 | 107 | 104 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 18 | mcts_grid_rd20_pr0.7_ec1.41 | mcts_hyperparam_grid | 56.3% | 34 | 80 | 103 | 109 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 19 | mcts_refine_rd45_pr0.9 | mcts_refined_grid | 52.7% | 35 | 86 | 96 | 105 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.9, "exploration_constant": 1.41}` |
| 20 | mcts_refine_rd45_pr0.95 | mcts_refined_grid | 51.1% | 39 | 88 | 92 | 104 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.95, "exploration_constant": 1.41}` |
| 21 | mcts_budget_robustness_tb1.0 | mcts_budget_robustness | 42.5% | 39 | 104 | 77 | 122 | max_days_reached | `{"time_budget_s": 1.0, "rollout_max_days": 45, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 22 | mcts_grid_rd20_pr0.85_ec1.41 | mcts_hyperparam_grid | 44.4% | 40 | 100 | 80 | 116 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 23 | mcts_grid_rd20_pr0.85_ec2.5 | mcts_hyperparam_grid | 44.4% | 40 | 100 | 80 | 118 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 24 | mcts_grid_rd45_pr0.7_ec0.7 | mcts_hyperparam_grid | 40.7% | 40 | 108 | 74 | 121 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 25 | mcts_grid_rd45_pr0.7_ec2.5 | mcts_hyperparam_grid | 40.7% | 40 | 108 | 74 | 125 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 26 | mcts_grid_rd45_pr0.7_ec1.41 | mcts_hyperparam_grid | 40.7% | 41 | 108 | 74 | 127 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 27 | mcts_refine_rd30_pr0.85 | mcts_refined_grid | 45.6% | 42 | 98 | 82 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 30, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 28 | mcts_refine_rd30_pr0.9 | mcts_refined_grid | 45.6% | 42 | 98 | 82 | 120 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 30, "proximity_ratio": 0.9, "exploration_constant": 1.41}` |
| 29 | mcts_grid_rd20_pr0.85_ec0.7 | mcts_hyperparam_grid | 42.5% | 42 | 104 | 77 | 119 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 30 | mcts_refine_rd45_pr0.8 | mcts_refined_grid | 39.8% | 42 | 109 | 72 | 126 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.8, "exploration_constant": 1.41}` |
| 31 | mcts_grid_rd45_pr0.5_ec0.7 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 32 | mcts_grid_rd45_pr0.5_ec1.41 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 33 | mcts_grid_rd45_pr0.5_ec2.5 | mcts_hyperparam_grid | 37.8% | 43 | 112 | 68 | 129 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 45, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 34 | mcts_grid_rd20_pr0.5_ec0.7 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 35 | mcts_grid_rd20_pr0.5_ec1.41 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 36 | mcts_grid_rd20_pr0.5_ec2.5 | mcts_hyperparam_grid | 43.3% | 45 | 102 | 78 | 117 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 20, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 37 | heuristic_maximal_opportunistic | structural_heuristic | 99.4% | 54 | 1 | 180 | 47 | max_days_reached | `{}` |
| 38 | baseline_greedy | baseline | 27.9% | 57 | 132 | 51 | 81 | max_days_reached | `{}` |
| 39 | mcts_refine_rd60_pr0.8 | mcts_refined_grid | 38.3% | 59 | 111 | 69 | 122 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 60, "proximity_ratio": 0.8, "exploration_constant": 1.41}` |
| 40 | mcts_refine_rd60_pr0.85 | mcts_refined_grid | 38.3% | 59 | 111 | 69 | 122 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 60, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 41 | mcts_refine_rd60_pr0.9 | mcts_refined_grid | 33.9% | 60 | 119 | 61 | 128 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 60, "proximity_ratio": 0.9, "exploration_constant": 1.41}` |
| 42 | mcts_refine_rd30_pr0.8 | mcts_refined_grid | 25.0% | 61 | 135 | 45 | 144 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 30, "proximity_ratio": 0.8, "exploration_constant": 1.41}` |
| 43 | mcts_grid_rd90_pr0.7_ec0.7 | mcts_hyperparam_grid | 11.1% | 63 | 160 | 20 | 162 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 0.7}` |
| 44 | mcts_refine_rd60_pr0.95 | mcts_refined_grid | 11.1% | 63 | 160 | 20 | 146 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 60, "proximity_ratio": 0.95, "exploration_constant": 1.41}` |
| 45 | mcts_grid_rd90_pr0.5_ec0.7 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 0.7}` |
| 46 | mcts_grid_rd90_pr0.5_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 1.41}` |
| 47 | mcts_grid_rd90_pr0.5_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.5, "exploration_constant": 2.5}` |
| 48 | mcts_grid_rd90_pr0.7_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 1.41}` |
| 49 | mcts_grid_rd90_pr0.7_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.7, "exploration_constant": 2.5}` |
| 50 | mcts_grid_rd90_pr0.85_ec0.7 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 0.7}` |
| 51 | mcts_grid_rd90_pr0.85_ec1.41 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 1.41}` |
| 52 | mcts_grid_rd90_pr0.85_ec2.5 | mcts_hyperparam_grid | 6.7% | 64 | 168 | 12 | 168 | max_days_reached | `{"time_budget_s": 2.0, "rollout_max_days": 90, "proximity_ratio": 0.85, "exploration_constant": 2.5}` |
| 53 | heuristic_corridor_sweep_pr0.5 | structural_heuristic | 28.3% | 67 | 129 | 51 | 49 | max_days_reached | `{"proximity_ratio": 0.5}` |
| 54 | heuristic_corridor_sweep_pr0.7 | structural_heuristic | 19.2% | 67 | 147 | 35 | 53 | max_days_reached | `{"proximity_ratio": 0.7}` |