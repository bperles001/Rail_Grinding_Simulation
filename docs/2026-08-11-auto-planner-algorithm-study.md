# Auto Planner algorithm study — Greedy vs Rolling-horizon ILP vs Simulated Annealing

Real network: `network_20251223_115340.json`, ZTO→ZCZ, 2026–2027, 2º KLD, 400 steps.

## Summary table

| Strategy | stop_reason | steps | maint. actions | movement days | maint. days | idle days | total days | segments over threshold |
|---|---|---|---|---|---|---|---|---|
| Greedy | year_limit | 344 | 26 | 630 | 101 | 0 | 731 | 92 |
| Rolling ILP (window=60d) | steps_limit | 400 | 47 | 125 | 240 | 0 | 365 | 23 |
| Simulated Annealing (window=60d, seed=1) | steps_limit | 400 | 105 | 221 | 366 | 0 | 587 | 48 |
| Simulated Annealing (window=60d, seed=2) | steps_limit | 400 | 33 | 68 | 163 | 0 | 231 | 28 |
| Simulated Annealing (window=60d, seed=3) | steps_limit | 400 | 77 | 186 | 285 | 0 | 471 | 50 |
| Simulated Annealing (window=60d) min/avg/max | - | - | 33/71.7/105 | - | - | - | 231/429.7/587 | - |
| Rolling ILP (window=90d) | year_limit | 194 | 88 | 206 | 526 | 0 | 732 | 48 |
| Simulated Annealing (window=90d, seed=1) | steps_limit | 400 | 54 | 112 | 289 | 0 | 401 | 18 |
| Simulated Annealing (window=90d, seed=2) | steps_limit | 400 | 65 | 94 | 358 | 0 | 452 | 27 |
| Simulated Annealing (window=90d, seed=3) | steps_limit | 400 | 56 | 135 | 319 | 0 | 454 | 24 |
| Simulated Annealing (window=90d) min/avg/max | - | - | 54/58.3/65 | - | - | - | 401/435.7/454 | - |
| Rolling ILP (window=120d) | steps_limit | 400 | 75 | 139 | 349 | 0 | 488 | 24 |
| Simulated Annealing (window=120d, seed=1) | year_limit | 214 | 109 | 198 | 532 | 0 | 730 | 20 |
| Simulated Annealing (window=120d, seed=2) | year_limit | 338 | 133 | 264 | 466 | 0 | 730 | 36 |
| Simulated Annealing (window=120d, seed=3) | year_limit | 204 | 109 | 175 | 555 | 0 | 730 | 25 |
| Simulated Annealing (window=120d) min/avg/max | - | - | 109/117.0/133 | - | - | - | 730/730.0/730 | - |
| Rolling ILP (window=180d) | steps_limit | 400 | 6 | 17 | 24 | 0 | 41 | 22 |
| Simulated Annealing (window=180d, seed=1) | steps_limit | 400 | 49 | 121 | 250 | 0 | 371 | 22 |
| Simulated Annealing (window=180d, seed=2) | steps_limit | 400 | 81 | 176 | 413 | 0 | 589 | 20 |
| Simulated Annealing (window=180d, seed=3) | steps_limit | 400 | 36 | 64 | 184 | 0 | 248 | 19 |
| Simulated Annealing (window=180d) min/avg/max | - | - | 36/55.3/81 | - | - | - | 248/402.7/589 | - |

## Notes

- Greedy has no planning window (1-hop lookahead), listed once for reference against every ILP/SA row.
- Simulated Annealing is stochastic: 3 seeds per window are run and reported individually plus a min/avg/max summary row.
- `segments_over_threshold_at_end` counts curva+tangente components still over their MTBT threshold when the run stops -- lower is better coverage.