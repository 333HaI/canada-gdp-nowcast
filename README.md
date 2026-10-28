# canada-gdp-nowcast

Nowcast of Canadian real GDP growth (expenditure-based, q/q at an annual
rate), re-estimated every Friday with a mixed-frequency dynamic factor model.

<!-- nowcast:start (rewritten by the weekly job) -->
Nowcast as of 2026-10-28: 2026Q3 2.2% (68%: 1.1 to 3.2), 2026Q4 1.8% (68%: -0.3 to 4.0).

Backtest 2010-2026 (excl. 2020Q1-2021Q1): RMSE 1.59 vs 2.23 for an AR(1) and 1.90 for a naive monthly GDP tracker.

Live: https://333hai.github.io/canada-gdp-nowcast/
<!-- nowcast:end -->

## Running it

```bash
pip install -r requirements.txt && pip install --no-deps -e .
python -m nowcast fetch      # download everything into data/vintages/<today>/
python -m nowcast nowcast    # fit and print the nowcast + what moved it
python -m nowcast update     # same, but also append to output/*.csv
python -m nowcast report     # write site/index.html
python -m nowcast backtest   # 2010 onwards, takes ~8 min
python -m pytest
```

FRED uses the API if `FRED_API_KEY` is set and the public CSV download if
not. Versions in `requirements.txt` are pinned on purpose. statsmodels 0.15
changes the EM step enough to break the fit, so upgrade only together with a
fresh backtest.

## Weekly job

`.github/workflows/weekly.yml` runs Fridays at 14:00 UTC, a few hours after
the Labour Force Survey comes out. It runs the tests, takes a snapshot,
refits, appends the nowcast and the news breakdown to `output/`, rebuilds the
page, deploys it to Pages and commits the data back. So the git log is the
audit trail.

To set it up on a new repo, add a `FRED_API_KEY` secret and set Pages to
deploy from GitHub Actions. GitHub turns off cron workflows on public repos
after 60 days with no activity, so check the Actions tab now and then.

## Data

Everything is defined in [config/series.yaml](config/series.yaml): vector
IDs, transformations, factor blocks and typical release lags. There are 20
monthly series (StatCan, Bank of Canada, FRED), and the target is quarterly
real GDP (v62305752).

A few details:

- Retail sales and building permits changed StatCan tables, so the old and
  new vectors are spliced. On overlap the old series is rescaled to the new
  one. Where they don't overlap, the growth rate at the seam is set to
  missing.
- Daily BoC rates are averaged to months.
- The monthly GDP flash estimate isn't in the WDS API, so it goes into
  `data/manual/gdp_flash.csv` by hand (`date,value,release_date`, % m/m).
- Each weekly pull is kept as-is in `data/vintages/YYYY-MM-DD/`. From
  2026-10-23 onwards that's a proper real-time archive.

## Model

statsmodels `DynamicFactorMQ`, fit by EM (Banbura & Modugno). Series go in
as log growth rates (first differences for rates and yields). Each block
gets one AR(1) factor and each series an AR(1) idiosyncratic term.
Quarterly GDP links to the monthly factors through the Mariano-Murasawa
weights. Mar-Dec 2020 is set to missing before fitting.

There are three blocks: `global` (everything), `real` (activity data) and
`output` (quarterly GDP plus the four monthly GDP series). The output block
lets quarterly GDP follow monthly GDP directly instead of only through the
broad factors. That's what fixed the late-quarter errors, see
[variants.md](output/backtest/variants.md).

Bands come from the smoothed state covariance. The news breakdown re-runs
last week's data through this week's parameters and splits the change into
one contribution per release, plus revisions.

## Backtest

Weekly nowcasts from 2010 for every quarter not yet published. A data point
counts as available once its reference period plus the usual release lag has
passed. Parameters are refit at the start of each quarter. Errors are in
annualized percentage points against today's GDP figures, excluding
2020Q1-2021Q1.

| made in | model | AR(1) | naive | n |
|---|---|---|---|---|
| month 1 of the quarter | 2.20 | 2.21 | 2.71 | 261 |
| month 2 | 1.90 | 2.14 | 2.10 | 260 |
| month 3 | 1.66 | 2.23 | 2.16 | 263 |
| 1st month after quarter end | 1.00 | 2.27 | 1.17 | 263 |
| 2nd month after quarter end | 0.64 | 2.30 | 0.59 | 261 |
| all | 1.59 | 2.23 | 1.90 | 1308 |

Diebold-Mariano (Newey-West, horizons pooled): p < 0.001 against the AR(1),
p = 0.04 against the naive tracker. The 68% and 90% bands contained the
outcome 69% and 90% of the time.

The AR(1) is fit on quarterly growth. The naive tracker is the growth in the
quarterly average of monthly GDP, with unpublished months filled at the
trailing 12-month average growth. Every individual nowcast is in
[output/backtest/](output/backtest/).

## Caveats

- It's pseudo real time. The inputs are today's revised data with fixed
  release lags, so revisions and actual release dates are ignored, and the
  scores are against current GDP rather than first releases. StatCan has
  real-time vintage tables for monthly GDP (36-10-0491), trade (12-10-0165),
  manufacturing (16-10-0014) and wholesale/retail, which would be the next
  step. I couldn't find one for quarterly expenditure GDP.
- 2020 is masked, so 2020Q1-2021Q1 are left out of the scores. With them in,
  the model is only about as good as the AR(1).
- I tried four block setups on the same sample and kept the best, so the
  RMSE is a bit flattering.
- The bands leave out parameter uncertainty.
- In the last month before release the naive tracker is still slightly
  better (0.59 vs 0.64). Filling in the flash estimates should help there.
- The BoC overnight rate series on Valet only starts in 2009.
