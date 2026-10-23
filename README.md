# Canadian GDP nowcast

Weekly nowcast of Canadian quarterly real GDP growth (expenditure-based,
annualized) from a mixed-frequency dynamic factor model (`DynamicFactorMQ`).

<!-- nowcast:start (rewritten by the weekly job) -->
**Latest nowcast (data as of 2026-10-23):** 2026Q3 **2.2%** (68% band 1.1 to 3.2%); 2026Q4 **1.8%** (68% band −0.3 to 4.0%).

**Backtest:** 2010–2026, excluding 2020Q1–2021Q1. RMSE is **1.59 pp**, against 2.23 for an AR(1) (29% lower) and 1.90 for a naive monthly-GDP tracker (16% lower).

**Live page:** https://333hai.github.io/canada-gdp-nowcast/
<!-- nowcast:end -->

## Run

```bash
pip install -r requirements.txt && pip install --no-deps -e .
python -m nowcast fetch        # pull all series, save data/vintages/<today>/
python -m nowcast nowcast      # fit, print nowcast + bands, and news vs the previous snapshot
python -m nowcast update       # same, and append to the live record in output/
python -m nowcast report       # build the page in site/
python -m nowcast backtest --name output_block   # ~8 min
python -m pytest
```

Set `FRED_API_KEY` to use the FRED API; without it the public FRED CSV
endpoint is used. Dependencies are pinned in `requirements.txt` to the
versions the backtest was run with; upgrade them deliberately and re-run the
backtest.

## Weekly pipeline

`.github/workflows/weekly.yml` runs every Friday at 14:00 UTC, after the
08:30 ET Labour Force Survey release. It can also be started by hand from the
Actions tab. Each run does the following:

1. Runs the tests, fetches every series and saves a dated snapshot.
2. Re-estimates the model and nowcasts each unpublished quarter, with 68% and
   90% bands.
3. Appends the nowcast and its news decomposition to
   `output/nowcast_history.csv` and `output/news_history.csv`. Rows are never
   edited. When StatCan first publishes a quarter that was nowcast, its value
   goes to `output/first_releases.csv`, which the live record is scored
   against.
4. Rebuilds the page and deploys it to GitHub Pages.
5. Commits the new data, so the repository history doubles as an audit trail.

One-time setup:

- Add a repository secret named `FRED_API_KEY`.
- Set Settings → Pages → Source to "GitHub Actions".
- GitHub disables scheduled workflows in public repositories after 60 days
  without activity. The weekly commit should prevent that, but check the
  Actions tab after two months.

## Data

All series, sources, vector IDs, transformations and release lags are in
[`config/series.yaml`](config/series.yaml): 20 monthly indicators from
Statistics Canada, the Bank of Canada and FRED, plus quarterly real GDP
(v62305752) as the target.

- Retail sales and building permits are spliced across StatCan table
  revisions (ratio splice on overlap; the growth rate at a no-overlap seam is
  set to missing).
- Daily BoC rates are averaged to months.
- The monthly GDP advance estimate is not available through the WDS API and is
  entered by hand in `data/manual/gdp_flash.csv` (`date,value,release_date`,
  value in % m/m).
- Each weekly pull is saved unchanged under `data/vintages/YYYY-MM-DD/`
  (`raw.csv` + `manifest.json`). From the first snapshot (2026-10-23) on,
  that archive is a genuine real-time dataset.

## Method

- **Transformations.** Series are converted to % log growth, or first
  differences for rates and yields, then standardized inside the model.
  Observations from March to December 2020 are set to missing before
  estimation.
- **Model.** `statsmodels` `DynamicFactorMQ`, estimated by EM (Bańbura–Modugno).
  Each block has one AR(1) factor, and each series has an AR(1) idiosyncratic
  component. Quarterly GDP enters through the Mariano–Murasawa aggregation of
  monthly growth.
- **Blocks.** There are three:
  - `global`: all series
  - `real`: real-activity indicators
  - `output`: quarterly GDP and the four monthly GDP-by-industry series
- **Why the `output` block.** It lets quarterly GDP track monthly GDP directly
  rather than only through the broad factors. It was added because it improved
  the backtest; see [the variant comparison](output/backtest/variants.md).
- **Bands.** The bands are Gaussian intervals from the smoothed state
  covariance.
- **News.** The weekly news decomposition re-filters last week's data with this
  week's parameters. It splits the change in each open quarter's nowcast into
  the contribution of each new release, plus revisions.

## Backtest

The backtest is pseudo-real-time:

- Nowcasts are made every Friday from 2010 on, for every quarter not yet
  published.
- An observation counts as available once its reference period has ended plus
  the series' typical release lag.
- Parameters are re-estimated at the start of each quarter, using only data
  available then.
- Results are scored against currently published GDP, in annualized pp.

RMSE by how far into the quarter the nowcast was made, excluding
2020Q1–2021Q1:

| Horizon | Model | AR(1) | Naive | n | vs AR(1) | vs naive |
|---|---|---|---|---|---|---|
| Month 1 of quarter | 2.20 | 2.21 | 2.71 | 261 | 0.99 | 0.81 |
| Month 2 | 1.90 | 2.14 | 2.10 | 260 | 0.89 | 0.90 |
| Month 3 | 1.66 | 2.23 | 2.16 | 263 | 0.75 | 0.77 |
| 1st month after quarter end | 1.00 | 2.27 | 1.17 | 263 | 0.44 | 0.86 |
| 2nd month after quarter end | 0.64 | 2.30 | 0.59 | 261 | 0.28 | 1.09 |
| **All** | **1.59** | 2.23 | 1.90 | 1308 | **0.71** | **0.84** |

Diebold–Mariano tests (Newey–West, all horizons pooled):

- **vs AR(1):** p < 0.001.
- **vs naive tracker:** p = 0.04.

The 68% and 90% bands contain the outcome 69% and 90% of the time. The
benchmarks are:

- **AR(1):** fitted on quarterly GDP growth.
- **Naive tracker:** quarterly growth of the average level of monthly GDP by
  industry. Months not yet published are filled at the trailing 12-month
  average growth.

Full output is in [`output/backtest/`](output/backtest/), including every
individual nowcast and the all-quarters table.

## Limitations

- **Pseudo, not true, real time.** Inputs are today's revised data, with
  availability rebuilt from fixed typical release lags. Real release dates
  vary, and revisions are ignored. Scores are against today's GDP figures, not
  the first release. StatCan does publish real-time vintage tables for monthly
  GDP (36-10-0491), trade (12-10-0165), real manufacturing (16-10-0014) and
  wholesale and retail sales; switching the inputs to these is a planned
  improvement. No equivalent table was found for quarterly expenditure-based
  GDP.
- **COVID.** 2020 data are masked, so nowcasts for 2020Q1–2021Q1 are
  uninformative and are excluded from the headline scores. With them included,
  the model is barely better than the AR(1) and worse than the naive tracker.
- **Specification search.** Four block specifications were compared on the
  same sample and the best one was kept, so the headline RMSE is slightly
  optimistic.
- **Bands.** They exclude parameter uncertainty.
- **Last month before release.** The naive tracker is still marginally better
  in that window (0.59 vs 0.64), when two of the quarter's three months of
  monthly GDP are already out.
- **Policy rate.** The overnight-rate series on BoC Valet starts in 2009.
