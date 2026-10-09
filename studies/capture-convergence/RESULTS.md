# Simulation results

Synthetic data only. Runs are zero-based; target requires three consecutive runs at CV <= 15%.
Target search starts at run 1, or run 8 for sustained change. Medians for target runs include successful trials only;
the reached column reports censored trials explicitly. Makespan sums cover the full 24-run horizon.

| Scenario | Policy | Reached | Median target run | Total migrations (median) | Sum of traversal makespans (median seconds) |
| --- | --- | --- | --- | --- | --- |
| cold | fixed_two | 12/12 | 4.0 | 19.0 | 5729.862 |
| cold | adaptive | 12/12 | 2.0 | 8.0 | 5812.488 |
| cold | fixed_six | 12/12 | 2.0 | 20.0 | 5411.458 |
| cold | outer_pid | 12/12 | 2.0 | 8.0 | 5818.097 |
| cold | gradient | 12/12 | 2.0 | 8.0 | 5812.488 |
| jitter | fixed_two | 12/12 | 1.0 | 43.0 | 4596.59 |
| jitter | adaptive | 12/12 | 1.0 | 13.5 | 4598.24 |
| jitter | fixed_six | 12/12 | 1.0 | 129.0 | 4634.288 |
| jitter | outer_pid | 12/12 | 1.0 | 13.5 | 4598.24 |
| jitter | gradient | 12/12 | 1.0 | 10.5 | 4577.016 |
| step | fixed_two | 12/12 | 13.0 | 17.0 | 7000.0 |
| step | adaptive | 12/12 | 13.0 | 11.0 | 7265.0 |
| step | fixed_six | 12/12 | 12.0 | 32.0 | 6900.0 |
| step | outer_pid | 12/12 | 13.0 | 11.0 | 7265.0 |
| step | gradient | 12/12 | 13.0 | 10.5 | 7265.0 |
| spike | fixed_two | 12/12 | 1.0 | 43.0 | 4750.31 |
| spike | adaptive | 12/12 | 1.0 | 15.0 | 4733.965 |
| spike | fixed_six | 12/12 | 1.0 | 128.0 | 4739.65 |
| spike | outer_pid | 12/12 | 1.0 | 15.0 | 4733.965 |
| spike | gradient | 12/12 | 1.0 | 11.0 | 4741.217 |
| indivisible | fixed_two | 0/12 | not reached | 0.0 | 22800.0 |
| indivisible | adaptive | 0/12 | not reached | 0.0 | 22800.0 |
| indivisible | fixed_six | 0/12 | not reached | 0.0 | 22800.0 |
| indivisible | outer_pid | 0/12 | not reached | 0.0 | 22800.0 |
| indivisible | gradient | 0/12 | not reached | 0.0 | 22800.0 |
