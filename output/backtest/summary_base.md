# Backtest: base

## RMSE, annualized pp — Excluding 2020Q1-2021Q1

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 2.21 | 2.21 | 2.71 | 261 | 1 | 0.82 |
| month 2 | 1.91 | 2.14 | 2.1 | 260 | 0.89 | 0.91 |
| month 3 | 1.7 | 2.23 | 2.16 | 263 | 0.76 | 0.79 |
| after Q end, month 1 | 1.27 | 2.27 | 1.17 | 263 | 0.56 | 1.09 |
| after Q end, month 2 | 1.17 | 2.3 | 0.59 | 261 | 0.51 | 1.99 |
| all horizons | 1.7 | 2.23 | 1.9 | 1308 | 0.76 | 0.89 |

- Diebold-Mariano vs ar1: stat -3.50, p = 0.000
- Diebold-Mariano vs naive: stat -1.30, p = 0.192
- Band coverage: 68% band 64%, 90% band 85%

## RMSE, annualized pp — All quarters

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 7.12 | 7.11 | 9.03 | 283 | 1 | 0.79 |
| month 2 | 7.82 | 7.83 | 8.72 | 283 | 1 | 0.9 |
| month 3 | 6.99 | 7.1 | 4.36 | 283 | 0.98 | 1.6 |
| after Q end, month 1 | 6.88 | 7.1 | 2.54 | 284 | 0.97 | 2.7 |
| after Q end, month 2 | 7.65 | 7.85 | 1.65 | 285 | 0.98 | 4.63 |
| all horizons | 7.3 | 7.41 | 6.09 | 1418 | 0.99 | 1.2 |

- Diebold-Mariano vs ar1: stat -1.98, p = 0.048
- Diebold-Mariano vs naive: stat 1.37, p = 0.170
- Band coverage: 68% band 59%, 90% band 79%
