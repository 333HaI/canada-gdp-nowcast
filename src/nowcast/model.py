"""DynamicFactorMQ wrapper: fit, nowcast with bands, and news decomposition.

The model (Bańbura & Modugno 2014, statsmodels' `DynamicFactorMQ`) is a
mixed-frequency dynamic factor model estimated by EM. Monthly series load on
the factor blocks listed in config/series.yaml; quarterly GDP growth is linked
to the monthly factors by the Mariano-Murasawa (1, 2, 3, 2, 1) weights, so the
quarter's value is the model's estimate at the quarter's last month. Missing
values and the ragged edge need no special treatment: the Kalman smoother
fills them in.

All growth rates inside the model are q/q (or m/m) log % changes; only the
reported nowcast is annualized.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from .config import Config
from .transform import annualize

BANDS = (0.68, 0.90)


@dataclass(frozen=True)
class Spec:
    """Model specification. `blocks` picks which config blocks are used:
    series keep only the blocks listed here (every series has `global`).
    The default won the 2010-2026 backtest against global-only, global+real
    and global+output (output/backtest/variants.md)."""
    blocks: tuple = ("global", "real", "output")
    factor_order: int = 1
    idiosyncratic_ar1: bool = True
    maxiter: int = 500
    tolerance: float = 1e-6


def prepare(monthly: pd.DataFrame, quarterly: pd.DataFrame, cfg: Config,
            end: pd.Period) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop empty columns and pad the monthly frame with missing rows up to
    `end` (the last month of the latest quarter to be nowcast)."""
    monthly = monthly.loc[:, _usable(monthly, 24)]
    quarterly = quarterly.loc[:, _usable(quarterly, 8)]
    if cfg.target not in quarterly:
        raise ValueError(f"target {cfg.target!r} has no observations")
    start = monthly.index[0]
    last = max(monthly.index[-1], end)
    monthly = monthly.reindex(pd.period_range(start, last, freq="M"))
    q_end = last.asfreq("Q")
    quarterly = quarterly.reindex(pd.period_range(start.asfreq("Q"), q_end, freq="Q"))
    return monthly, quarterly


def _usable(df: pd.DataFrame, min_obs: int) -> list:
    """Columns the model can estimate: enough observations and not constant
    (e.g. the policy-rate change during the 2009-10 effective lower bound)."""
    return [c for c in df if df[c].count() >= min_obs and df[c].std() > 0]


def factor_map(columns, cfg: Config, spec: Spec) -> dict:
    return {k: [b for b in cfg.get(k).blocks if b in spec.blocks] for k in columns}


def build(monthly, quarterly, cfg: Config, spec: Spec) -> DynamicFactorMQ:
    factors = factor_map(list(monthly) + list(quarterly), cfg, spec)
    return DynamicFactorMQ(
        monthly, endog_quarterly=quarterly, factors=factors,
        factor_orders=spec.factor_order, idiosyncratic_ar1=spec.idiosyncratic_ar1,
        standardize=True,
    )


def fit(monthly, quarterly, cfg: Config, spec: Spec = Spec(), start_params=None):
    mod = build(monthly, quarterly, cfg, spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return mod.fit(start_params=start_params, disp=False,
                       maxiter=spec.maxiter, tolerance=spec.tolerance)


def refilter(res, monthly, quarterly):
    """Same parameters and standardization, new data (a different vintage)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return res.apply(monthly, endog_quarterly=quarterly, retain_standardization=True)


def nowcast(res, quarters, target: str) -> pd.DataFrame:
    """Annualized nowcast and 68% / 90% bands for each quarter in `quarters`.

    Bands are Gaussian intervals from the smoothed state covariance (parameter
    uncertainty is not included), mapped through the annualization.
    """
    quarters = [pd.Period(q, freq="Q") for q in quarters]
    months = [q.asfreq("M", how="end") for q in quarters]
    pred = res.get_prediction(start=min(months), end=max(months), information_set="smoothed")
    mean = pred.predicted_mean[target]
    sd = np.sqrt(pred.var_pred_mean[target]) if hasattr(pred.var_pred_mean, "columns") \
        else _sd_from_conf_int(pred, target)
    rows = []
    for q, m in zip(quarters, months):
        mu, s = float(mean.loc[m]), float(sd.loc[m])
        row = {"quarter": str(q), "qoq": mu, "nowcast": float(annualize(mu)), "sd_qoq": s}
        for b in BANDS:
            z = stats.norm.ppf(0.5 + b / 2)
            tag = int(round(b * 100))
            row[f"lo{tag}"] = float(annualize(mu - z * s))
            row[f"hi{tag}"] = float(annualize(mu + z * s))
        rows.append(row)
    return pd.DataFrame(rows).set_index("quarter")


def _sd_from_conf_int(pred, target):
    # conf_int is reported in original units; var_pred_mean is standardized
    ci = pred.conf_int(alpha=2 * stats.norm.sf(1))  # +/- 1 sd
    cols = [c for c in ci.columns if c.endswith(target)]
    return (ci[cols[1]] - ci[cols[0]]) / 2


def news(res_new, res_old, quarter, target: str, cfg: Config | None = None) -> pd.DataFrame:
    """Which data releases moved the nowcast for `quarter` between two vintages.

    Returns one row per updated series with its impact on the q/q and on the
    annualized nowcast, plus data revisions as one extra row. Impacts sum to
    the change in the nowcast (`attrs['prev']` -> `attrs['post']`).
    """
    month = pd.Period(quarter, freq="Q").asfreq("M", how="end")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nr = res_new.news(res_old, impact_date=month, impacted_variable=target,
                          comparison_type="previous")
    rows = []
    det = nr.details_by_impact
    if det is not None and len(det):
        d = det.reset_index()
        col = "updated variable" if "updated variable" in d else d.columns[2]
        g = d.groupby(col)["impact"].sum()
        for var, imp in g.items():
            rows.append({"series": var, "impact_qoq": float(imp)})
    rev = 0.0
    if nr.revision_impacts is not None and target in getattr(nr.revision_impacts, "columns", []):
        rev = float(np.nansum(nr.revision_impacts[target].to_numpy()))
    if abs(rev) > 1e-12:
        rows.append({"series": "(revisions)", "impact_qoq": rev})
    out = pd.DataFrame(rows, columns=["series", "impact_qoq"])
    prev = float(nr.prev_impacted_forecasts[target].iloc[0])
    post = float(nr.post_impacted_forecasts[target].iloc[0])
    # scale q/q impacts so the annualized ones add up exactly to the change
    # in the annualized nowcast (annualization is not linear)
    d_ann = float(annualize(post) - annualize(prev))
    scale = d_ann / (post - prev) if abs(post - prev) > 1e-12 else 4 * np.exp(4 * post / 100)
    out["impact_ann"] = out["impact_qoq"] * scale
    if cfg is not None:
        names = {s.key: s.name for s in cfg.series}
        out["name"] = out["series"].map(names).fillna(out["series"])
    out = out.reindex(out["impact_qoq"].abs().sort_values(ascending=False).index)
    out.attrs.update({"quarter": str(quarter), "prev_qoq": prev, "post_qoq": post,
                      "prev": float(annualize(prev)), "post": float(annualize(post))})
    return out.reset_index(drop=True)


def open_quarters(quarterly: pd.DataFrame, target: str, today: pd.Timestamp) -> list[pd.Period]:
    """Quarters to nowcast: every quarter after the last published one, up to
    and including the quarter containing `today`."""
    last_pub = quarterly[target].dropna().index.max()
    current = pd.Period(today, freq="Q")
    return list(pd.period_range(last_pub + 1, current, freq="Q"))
