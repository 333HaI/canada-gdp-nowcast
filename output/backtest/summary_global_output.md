# Backtest: global_output

## RMSE, annualized pp — Excluding 2020Q1-2021Q1

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 2.21 | 2.21 | 2.71 | 261 | 1 | 0.82 |
| month 2 | 1.94 | 2.14 | 2.1 | 260 | 0.91 | 0.93 |
| month 3 | 1.63 | 2.23 | 2.16 | 263 | 0.73 | 0.75 |
| after Q end, month 1 | 1.1 | 2.27 | 1.17 | 263 | 0.48 | 0.94 |
| after Q end, month 2 | 0.83 | 2.3 | 0.59 | 261 | 0.36 | 1.41 |
| all horizons | 1.62 | 2.23 | 1.9 | 1308 | 0.73 | 0.85 |

- Diebold-Mariano vs ar1: stat -3.50, p = 0.000
- Diebold-Mariano vs naive: stat -1.81, p = 0.070
- Band coverage: 68% band 64%, 90% band 87%

## RMSE, annualized pp — All quarters

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 7.13 | 7.11 | 9.03 | 283 | 1 | 0.79 |
| month 2 | 7.79 | 7.83 | 8.72 | 283 | 1 | 0.89 |
| month 3 | 6.96 | 7.1 | 4.36 | 283 | 0.98 | 1.6 |
| after Q end, month 1 | 6.83 | 7.1 | 2.54 | 284 | 0.96 | 2.69 |
| after Q end, month 2 | 7.58 | 7.85 | 1.65 | 285 | 0.97 | 4.58 |
| all horizons | 7.27 | 7.41 | 6.09 | 1418 | 0.98 | 1.19 |

- Diebold-Mariano vs ar1: stat -2.85, p = 0.004
- Diebold-Mariano vs naive: stat 1.35, p = 0.178
- Band coverage: 68% band 60%, 90% band 81%
