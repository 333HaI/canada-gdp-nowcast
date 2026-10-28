# Does the GDP flash estimate help?

Tested 2026-10-28. Same snapshot (2026-10-28) for both runs, default spec
(global + real + output), with and without `gdp_flash`. Runs:
`predictions_output_block_noflash_1028.csv` and
`predictions_output_block_flash.csv`.

The flash series starts in 2020-03, but 2020 is masked and the model needs 24
observations, so it only enters from early 2023. Before 2023Q1 the two runs
are identical (max difference 0.0), which is the leakage check.

Since 2023Q1 (14 quarters, 299 nowcasts), RMSE in annualized pp:

| made in | no flash | flash | ratio |
|---|---|---|---|
| month 1 | 1.918 | 1.928 | 1.005 |
| month 2 | 1.728 | 1.695 | 0.981 |
| month 3 | 1.469 | 1.446 | 0.984 |
| after q end, month 1 | 1.046 | 1.085 | 1.037 |
| after q end, month 2 | 0.763 | 0.772 | 1.011 |
| all | 1.446 | 1.442 | 0.997 |

Diebold-Mariano flash vs no flash: stat -0.43, p = 0.67. Band coverage
62/95% without, 62/94% with.

The flash data itself is fine. Ex 2020 it correlates 0.72 with today's
monthly GDP growth, RMSE 0.27 against a 0.37 standard deviation, and it comes
out a median 30 days after the end of its month, matching `release_lag`.

So it's not the data, it's the setup. In a factor model the flash only
moves quarterly GDP through the common factors, but what it really tells you
is the missing month of monthly GDP, which is mostly the GDP-specific part
the factors don't carry. The naive tracker uses that part directly, which is
why it still wins in the last month. Using the flash properly needs it tied
to monthly GDP itself (a bridge step after the DFM), not another loading.

Decision: keep scraping and archiving it (`model: false`), leave it out of
the fit.
