# Backtest: output_block_noflash_1028

## RMSE, annualized pp — Excluding 2020Q1-2021Q1

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 2.2 | 2.21 | 2.71 | 261 | 0.99 | 0.81 |
| month 2 | 1.9 | 2.14 | 2.1 | 260 | 0.89 | 0.9 |
| month 3 | 1.66 | 2.23 | 2.16 | 263 | 0.75 | 0.77 |
| after Q end, month 1 | 1 | 2.27 | 1.17 | 263 | 0.44 | 0.86 |
| after Q end, month 2 | 0.64 | 2.3 | 0.59 | 261 | 0.28 | 1.09 |
| all horizons | 1.59 | 2.23 | 1.9 | 1308 | 0.71 | 0.84 |

- Diebold-Mariano vs ar1: stat -3.57, p = 0.000
- Diebold-Mariano vs naive: stat -2.05, p = 0.041
- Band coverage: 68% band 69%, 90% band 90%

## RMSE, annualized pp — All quarters

|  | model | ar1 | naive | n | model/ar1 | model/naive |
|---|---|---|---|---|---|---|
| month 1 | 7.12 | 7.11 | 9.03 | 283 | 1 | 0.79 |
| month 2 | 7.79 | 7.83 | 8.72 | 283 | 0.99 | 0.89 |
| month 3 | 6.96 | 7.1 | 4.36 | 283 | 0.98 | 1.6 |
| after Q end, month 1 | 6.83 | 7.1 | 2.54 | 284 | 0.96 | 2.69 |
| after Q end, month 2 | 7.57 | 7.85 | 1.65 | 285 | 0.97 | 4.58 |
| all horizons | 7.26 | 7.41 | 6.09 | 1418 | 0.98 | 1.19 |

- Diebold-Mariano vs ar1: stat -2.72, p = 0.007
- Diebold-Mariano vs naive: stat 1.34, p = 0.181
- Band coverage: 68% band 64%, 90% band 84%
