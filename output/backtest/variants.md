# Block specifications compared (ex 2020Q1-2021Q1, annualized pp)

|  | RMSE all | RMSE month 3 | RMSE after Q end | vs AR(1) | vs naive | DM p vs naive | 68% cover | 90% cover |
|---|---|---|---|---|---|---|---|---|
| global (`global_only`) | 1.65 | 1.61 | 1.09 | 0.74 | 0.87 | 0.1 | 0.61 | 0.84 |
| global + real (`base`) | 1.7 | 1.7 | 1.22 | 0.76 | 0.89 | 0.19 | 0.64 | 0.85 |
| global + output (`global_output`) | 1.62 | 1.63 | 0.97 | 0.73 | 0.85 | 0.07 | 0.64 | 0.87 |
| global + real + output (`output_block`) | 1.59 | 1.66 | 0.84 | 0.71 | 0.84 | 0.04 | 0.69 | 0.9 |
