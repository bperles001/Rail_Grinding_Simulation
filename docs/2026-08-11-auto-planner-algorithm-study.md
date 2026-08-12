# Auto Planner algorithm study — Greedy vs Rolling-horizon ILP vs Simulated Annealing

Real network: `network_20251223_115340.json`, ZTO→ZCZ, 2026–2027, 2º KLD, 400 steps.

## Summary table

| Strategy | stop_reason | steps | maint. actions | movement days | maint. days | idle days | total days | segments over threshold |
|---|---|---|---|---|---|---|---|---|
| Greedy | year_limit | 342 | 27 | 628 | 103 | 0 | 731 | 92 |
| Rolling ILP (window=60d) | year_limit | 253 | 101 | 274 | 456 | 0 | 730 | 42 |
| Simulated Annealing (window=60d, seed=1) | year_limit | 226 | 104 | 229 | 501 | 0 | 730 | 46 |
| Simulated Annealing (window=60d, seed=2) | year_limit | 204 | 98 | 201 | 529 | 0 | 730 | 28 |
| Simulated Annealing (window=60d, seed=3) | year_limit | 297 | 128 | 308 | 423 | 0 | 731 | 60 |
| Simulated Annealing (window=60d) min/avg/max | - | - | 98/110.0/128 | - | - | - | 730/730.3/731 | - |
| Rolling ILP (window=90d) | year_limit | 290 | 101 | 313 | 418 | 0 | 731 | 45 |
| Simulated Annealing (window=90d, seed=1) | year_limit | 288 | 129 | 290 | 442 | 0 | 732 | 42 |
| Simulated Annealing (window=90d, seed=2) | year_limit | 189 | 94 | 182 | 548 | 0 | 730 | 21 |
| Simulated Annealing (window=90d, seed=3) | year_limit | 297 | 128 | 308 | 423 | 0 | 731 | 60 |
| Simulated Annealing (window=90d) min/avg/max | - | - | 94/117.0/129 | - | - | - | 730/731.0/732 | - |
| Rolling ILP (window=120d) | year_limit | 313 | 99 | 303 | 430 | 0 | 733 | 51 |
| Simulated Annealing (window=120d, seed=1) | year_limit | 286 | 131 | 281 | 451 | 0 | 732 | 44 |
| Simulated Annealing (window=120d, seed=2) | year_limit | 308 | 111 | 306 | 425 | 0 | 731 | 66 |
| Simulated Annealing (window=120d, seed=3) | year_limit | 248 | 100 | 262 | 469 | 0 | 731 | 46 |
| Simulated Annealing (window=120d) min/avg/max | - | - | 100/114.0/131 | - | - | - | 731/731.3/732 | - |
| Rolling ILP (window=180d) | year_limit | 154 | 77 | 151 | 589 | 0 | 740 | 54 |
| Simulated Annealing (window=180d, seed=1) | year_limit | 260 | 111 | 241 | 491 | 0 | 732 | 37 |
| Simulated Annealing (window=180d, seed=2) | year_limit | 258 | 95 | 271 | 460 | 0 | 731 | 40 |
| Simulated Annealing (window=180d, seed=3) | year_limit | 260 | 100 | 264 | 466 | 0 | 730 | 36 |
| Simulated Annealing (window=180d) min/avg/max | - | - | 95/102.0/111 | - | - | - | 730/731.0/732 | - |

## Notes

- Greedy has no planning window (1-hop lookahead), listed once for reference against every ILP/SA row.
- Simulated Annealing is stochastic: 3 seeds per window are run and reported individually plus a min/avg/max summary row.
- `segments_over_threshold_at_end` counts curva+tangente components still over their MTBT threshold when the run stops -- lower is better coverage.