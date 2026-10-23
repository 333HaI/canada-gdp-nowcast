# Backtest: global_only

## RMSE, annualized pp — Excluding 2020Q1-2021Q1

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 2.23 | 2.21 | 2.71 | 261 | 1.01 | 0.83 |
| month 2 | 1.92 | 2.14 | 2.1 | 260 | 0.89 | 0.91 |
| month 3 | 1.61 | 2.23 | 2.16 | 263 | 0.72 | 0.75 |
| after Q end, month 1 | 1.18 | 2.27 | 1.17 | 263 | 0.52 | 1.01 |
| after Q end, month 2 | 0.98 | 2.3 | 0.59 | 261 | 0.43 | 1.67 |
| all horizons | 1.65 | 2.23 | 1.9 | 1308 | 0.74 | 0.87 |

- Diebold-Mariano vs ar1: stat -3.42, p = 0.001
- Diebold-Mariano vs naive: stat -1.65, p = 0.099
- Band coverage: 68% band 61%, 90% band 84%

## RMSE, annualized pp — All quarters

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 7.14 | 7.11 | 9.03 | 283 | 1 | 0.79 |
| month 2 | 7.81 | 7.83 | 8.72 | 283 | 1 | 0.9 |
| month 3 | 6.97 | 7.1 | 4.36 | 283 | 0.98 | 1.6 |
| after Q end, month 1 | 6.86 | 7.1 | 2.54 | 284 | 0.97 | 2.7 |
| after Q end, month 2 | 7.61 | 7.85 | 1.65 | 285 | 0.97 | 4.6 |
| all horizons | 7.29 | 7.41 | 6.09 | 1418 | 0.98 | 1.2 |

- Diebold-Mariano vs ar1: stat -2.19, p = 0.028
- Diebold-Mariano vs naive: stat 1.36, p = 0.174
- Band coverage: 68% band 56%, 90% band 78%
