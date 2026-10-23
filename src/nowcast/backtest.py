"""Pseudo-real-time backtest of the nowcast against two benchmarks.

For each weekly vintage date v (Fridays from 2010 on):
  * every observation is treated as published iff
        end of its reference period + series release_lag <= v
    which rebuilds the ragged edge from typical release lags;
  * every quarter not yet published at v, up to the quarter containing v, is
    nowcast by the model and by both benchmarks;
  * model parameters are re-estimated (EM, warm-started) at the first vintage
    of each calendar quarter using only data available then, and held fixed
    for the rest of the quarter's vintages.

Limitations (stated in the README): data are the latest vintage, so the
backtest ignores revisions; true first releases are not used for the inputs
or for scoring. Scores are against today's published GDP.

Benchmarks
  ar1    AR(1) on q/q GDP growth, OLS on all available quarters, iterated to
         the target quarter.
  naive  Quarterly growth of the average level of monthly GDP by industry.
         Months not yet published are filled at the average m/m growth of
         the 12 latest published months.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import model as M
from .config import ROOT, Config
from .transform import annualize, build_levels, build_panel

log = logging.getLogger(__name__)

OUT_DIR = ROOT / "output" / "backtest"
COVID = (pd.Period("2020Q1", "Q"), pd.Period("2021Q1", "Q"))


# ------------------------------------------------------------- ragged edge

def release_dates(frame: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Date each cell becomes public: end of period + the series' lag."""
    ends = frame.index.to_timestamp(how="end").normalize()
    return pd.DataFrame(
        {k: ends + pd.Timedelta(days=cfg.get(k).release_lag) for k in frame},
        index=frame.index,
    )


def as_of(frame: pd.DataFrame, released: pd.DataFrame, vintage: pd.Timestamp) -> pd.DataFrame:
    return frame.where(released <= vintage)


def open_quarters(q_vintage: pd.Series, vintage: pd.Timestamp) -> list[pd.Period]:
    return list(pd.period_range(q_vintage.dropna().index.max() + 1,
                                pd.Period(vintage, freq="Q"), freq="Q"))


# --------------------------------------------------------------- benchmarks

def ar1_forecast(y: pd.Series, target: pd.Period) -> float:
    y = y.dropna()
    pairs = pd.DataFrame({"x": y.shift(1, freq="Q"), "z": y}).dropna()
    X = np.column_stack([np.ones(len(pairs)), pairs["x"]])
    c, phi = np.linalg.lstsq(X, pairs["z"].to_numpy(), rcond=None)[0]
    last_q, f = y.index.max(), float(y.iloc[-1])
    for _ in range((target - last_q).n):
        f = c + phi * f
    return f


def naive_forecast(levels: pd.Series, target: pd.Period) -> float:
    """Levels: monthly GDP as published at the vintage (NaN = not yet out)."""
    lv = levels.dropna()
    g = np.log(lv).diff().dropna().tail(12).mean()
    months = pd.period_range(target.asfreq("M", "start") - 3, target.asfreq("M", "end"), freq="M")
    last = lv.index.max()
    log_lv = np.log(lv).reindex(lv.index.union(months))
    for m in months:
        if m > last:
            log_lv.loc[m] = np.log(lv.iloc[-1]) + g * (m - last).n
    prev = np.exp(log_lv.loc[months[:3]]).mean()
    cur = np.exp(log_lv.loc[months[3:]]).mean()
    return 100 * np.log(cur / prev)


# ----------------------------------------------------------------- main loop

def run(raw: pd.DataFrame, cfg: Config, spec: M.Spec = M.Spec(),
        start: str = "2010-01-01", end: str | None = None, step_days: int = 7,
        first_target: str = "2010Q1") -> pd.DataFrame:
    monthly, quarterly = build_panel(raw, cfg)            # masked, for the model
    _, q_unmasked = build_panel(raw, cfg, mask=False)       # truth
    m_levels, _, _ = build_levels(raw, cfg)
    gdp_lv = m_levels["gdp_m"]
    rel_m, rel_q = release_dates(monthly, cfg), release_dates(quarterly, cfg)
    # publication status comes from the unmasked target: a masked 2020 quarter
    # is still published, it is just not used for estimation
    published = q_unmasked[cfg.target]
    rel_target = release_dates(q_unmasked, cfg)[cfg.target]
    rel_lv = release_dates(m_levels[["gdp_m"]], cfg)["gdp_m"]
    truth = q_unmasked[cfg.target]
    last_truth = truth.dropna().index.max()

    vintages = pd.date_range(start, end or pd.Timestamp.today(), freq=f"{step_days}D")
    rows, res, params, fit_q, cols = [], None, None, None, None
    t0 = time.time()
    for i, v in enumerate(vintages):
        q_now = pd.Period(v, freq="Q")
        end_m = q_now.asfreq("M", "end")
        mv = as_of(monthly, rel_m, v).loc[:end_m]
        qv = as_of(quarterly, rel_q, v).loc[:q_now]
        targets = [t for t in open_quarters(published.where(rel_target <= v), v)
                   if pd.Period(first_target, "Q") <= t <= last_truth]
        if not targets:
            continue
        if res is None or q_now != fit_q:
            mv_fit, qv_fit = M.prepare(mv, qv, cfg, end_m)
            cols = (list(mv_fit), list(qv_fit))
            try:
                res = M.fit(mv_fit, qv_fit, cfg, spec, start_params=params)
            except Exception:  # shape changed (new series came online): cold start
                res = M.fit(mv_fit, qv_fit, cfg, spec)
            params, fit_q = res.params, q_now
            log.info("refit %s (%d/%d vintages, %.0fs)", q_now, i, len(vintages), time.time() - t0)
        mv_p, qv_p = M.prepare(mv, qv, cfg, end_m)
        mv_p, qv_p = mv_p.reindex(columns=cols[0]), qv_p.reindex(columns=cols[1])
        r = M.refilter(res, mv_p, qv_p)
        nc = M.nowcast(r, targets, cfg.target)
        q_avail = qv[cfg.target]
        lv_avail = gdp_lv.where(rel_lv <= v)
        for t in targets:
            qs = t.asfreq("D", "start").to_timestamp()
            rows.append({
                "vintage": v.date(), "target": str(t),
                "days": (v - qs).days,
                "actual": float(annualize(truth.loc[t])),
                "model": nc.loc[str(t), "nowcast"],
                "model_sd_qoq": nc.loc[str(t), "sd_qoq"],
                "ar1": float(annualize(ar1_forecast(q_avail, t))),
                "naive": float(annualize(naive_forecast(lv_avail, t))),
                "covid": COVID[0] <= t <= COVID[1],
            })
    out = pd.DataFrame(rows)
    out["month"] = np.minimum(out["days"] // 30 + 1, 5)  # 1-3 in quarter, 4-5 after
    return out


# ----------------------------------------------------------------- scoring

MODELS = ("model", "ar1", "naive")
HORIZON_LABEL = {1: "month 1", 2: "month 2", 3: "month 3",
                 4: "after Q end, month 1", 5: "after Q end, month 2"}


def score(pred: pd.DataFrame, exclude_covid: bool = True) -> pd.DataFrame:
    d = pred[~pred["covid"]] if exclude_covid else pred
    def rmse(g):
        return pd.Series({m: np.sqrt(np.mean((g[m] - g["actual"]) ** 2)) for m in MODELS}
                         | {"n": len(g)})
    by = d.groupby("month").apply(rmse, include_groups=False)
    by.index = [HORIZON_LABEL[i] for i in by.index]
    allrow = rmse(d).to_frame("all horizons").T
    t = pd.concat([by, allrow])
    t["model/ar1"] = t["model"] / t["ar1"]
    t["model/naive"] = t["model"] / t["naive"]
    t["n"] = t["n"].astype(int)
    return t


def coverage(pred: pd.DataFrame, exclude_covid: bool = True) -> pd.Series:
    """Share of actuals inside the model's 68% / 90% bands (q/q scale)."""
    from scipy import stats
    d = pred[~pred["covid"]] if exclude_covid else pred
    lq = lambda a: 25 * np.log1p(np.asarray(a) / 100)  # annualized -> q/q log %
    z = np.abs(lq(d["actual"]) - lq(d["model"])) / d["model_sd_qoq"]
    return pd.Series({f"{b:.0%}": float(np.mean(z <= stats.norm.ppf(0.5 + b / 2))) for b in (0.68, 0.90)})


def dm_test(pred: pd.DataFrame, bench: str, exclude_covid: bool = True) -> tuple[float, float]:
    """Diebold-Mariano on squared errors, model vs `bench`, all horizons pooled.
    Newey-West variance with lag = 13 weekly vintages (overlapping nowcasts of
    the same quarter are strongly correlated). Negative stat = model better."""
    from scipy import stats
    d = pred[~pred["covid"]] if exclude_covid else pred
    d = d.sort_values(["vintage", "target"])
    loss = (d["model"] - d["actual"]) ** 2 - (d[bench] - d["actual"]) ** 2
    x = loss.to_numpy() - loss.mean()
    n, L = len(x), 26
    var = x @ x / n + 2 * sum((1 - k / (L + 1)) * (x[k:] @ x[:-k]) / n for k in range(1, L + 1))
    stat = loss.mean() / np.sqrt(var / n)
    return float(stat), float(2 * stats.norm.sf(abs(stat)))


def markdown_table(df: pd.DataFrame) -> str:
    cols = [""] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        lines.append("| " + " | ".join([str(idx)] + [f"{v:g}" for v in row]) + " |")
    return "\n".join(lines)


def save(pred: pd.DataFrame, name: str, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pred.to_csv(out_dir / f"predictions_{name}.csv", index=False)
    lines = [f"# Backtest: {name}", ""]
    for excl, title in ((True, "Excluding 2020Q1-2021Q1"), (False, "All quarters")):
        t = score(pred, excl)
        lines += [f"## RMSE, annualized pp — {title}", "", markdown_table(t.round(2)), ""]
        for b in ("ar1", "naive"):
            s, p = dm_test(pred, b, excl)
            lines.append(f"- Diebold-Mariano vs {b}: stat {s:.2f}, p = {p:.3f}")
        cov = coverage(pred, excl)
        lines += [f"- Band coverage: 68% band {cov['68%']:.0%}, 90% band {cov['90%']:.0%}", ""]
    path = out_dir / f"summary_{name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def compare(names: dict[str, str], out_dir: Path = OUT_DIR) -> Path:
    """Overall ex-COVID scores for several saved runs, one row per variant."""
    rows = []
    for name, label in names.items():
        pred = pd.read_csv(out_dir / f"predictions_{name}.csv")
        t = score(pred)
        cov = coverage(pred)
        rows.append({
            "variant": f"{label} (`{name}`)",
            "RMSE all": t.loc["all horizons", "model"],
            "RMSE month 3": t.loc["month 3", "model"],
            "RMSE after Q end": np.sqrt(np.mean(
                (pred.loc[~pred.covid & (pred.month >= 4), "model"]
                 - pred.loc[~pred.covid & (pred.month >= 4), "actual"]) ** 2)),
            "vs AR(1)": t.loc["all horizons", "model/ar1"],
            "vs naive": t.loc["all horizons", "model/naive"],
            "DM p vs naive": dm_test(pred, "naive")[1],
            "68% cover": cov["68%"], "90% cover": cov["90%"],
        })
    df = pd.DataFrame(rows).set_index("variant").round(2)
    path = out_dir / "variants.md"
    path.write_text("# Block specifications compared (ex 2020Q1-2021Q1, annualized pp)\n\n"
                    + markdown_table(df) + "\n", encoding="utf-8")
    return path
