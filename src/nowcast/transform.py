"""Turn a raw snapshot into the stationary panel the model is estimated on.

Steps, in order:
  1. splice   series with several source ids are joined into one level series
  2. pivot    to a wide monthly frame (PeriodIndex 'M') and quarterly frame ('Q')
  3. transform each column per its `transform` in config/series.yaml
  4. mask     observations inside settings.mask windows become NaN

Standardization (demean, unit variance) is left to DynamicFactorMQ, which does
it internally with `standardize=True` and maps forecasts back to original
units. `standardize()` below is the same operation for use outside the model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config, Series


def splice(levels: dict[str, pd.Series], ids: tuple) -> pd.Series:
    """Join level series ordered oldest -> newest.

    Where two pieces overlap, the newer one is kept and the older one is
    rescaled so the levels match at the first common period: growth rates of
    each piece are preserved exactly. With no overlap the pieces are simply
    concatenated, which leaves one invalid growth rate at the seam; that
    period is set to NaN by `transform_series` via the `seams` attribute.
    """
    out = levels[ids[0]].dropna()
    seams = []
    for sid in ids[1:]:
        new = levels[sid].dropna()
        common = out.index.intersection(new.index)
        if len(common):
            t0 = common[0]
            out = out * (new.loc[t0] / out.loc[t0])
        else:
            seams.append(new.index[0])
        out = pd.concat([out[out.index < new.index[0]], new])
    out.attrs["seams"] = seams
    return out


def build_levels(raw: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Wide level frames (monthly, quarterly) plus splice seams per key."""
    cols = {"M": {}, "Q": {}}
    seams = {}
    for s in cfg.series:
        sub = raw[raw["key"] == s.key]
        if sub.empty:
            continue
        pieces = {}
        for sid in s.ids:
            g = sub[sub["source_id"] == str(sid)]
            pieces[str(sid)] = pd.Series(
                g["value"].to_numpy(dtype=float),
                index=pd.PeriodIndex(g["date"], freq=s.freq),
            ).groupby(level=0).last()
        present = tuple(i for i in s.ids if i in pieces and not pieces[i].dropna().empty)
        if not present:
            continue
        ser = splice(pieces, present)
        seams[s.key] = ser.attrs["seams"]
        cols[s.freq][s.key] = ser
    monthly = _wide(cols["M"], "M")
    quarterly = _wide(cols["Q"], "Q")
    return monthly, quarterly, seams


def _wide(cols: dict, freq: str) -> pd.DataFrame:
    if not cols:
        return pd.DataFrame(index=pd.PeriodIndex([], freq=freq))
    df = pd.DataFrame(cols).sort_index()
    full = pd.period_range(df.index.min(), df.index.max(), freq=freq)
    return df.reindex(full)


def transform_series(x: pd.Series, how: str, seams=()) -> pd.Series:
    if how == "dlog":
        x = x.where(x > 0)
        y = 100 * np.log(x).diff()
    elif how == "diff":
        y = x.diff()
    elif how == "level":
        y = x.copy()
    else:
        raise ValueError(f"unknown transform {how!r}")
    for p in seams:
        if p in y.index:
            y.loc[p] = np.nan
    return y


def apply_mask(df: pd.DataFrame, windows) -> pd.DataFrame:
    """Set rows inside each [start, end] window (inclusive, 'YYYY-MM') to NaN."""
    df = df.copy()
    if df.empty:
        return df
    for start, end in windows:
        lo = pd.Period(start, freq="M").asfreq(df.index.freq, how="start")
        hi = pd.Period(end, freq="M").asfreq(df.index.freq, how="end")
        df.loc[(df.index >= lo) & (df.index <= hi)] = np.nan
    return df


def build_panel(raw: pd.DataFrame, cfg: Config, mask: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stationary monthly and quarterly frames, ready for DynamicFactorMQ."""
    monthly, quarterly, seams = build_levels(raw, cfg)
    out = []
    for frame in (monthly, quarterly):
        t = pd.DataFrame(
            {k: transform_series(frame[k], cfg.get(k).transform, seams.get(k, ())) for k in frame},
            index=frame.index,
        )
        # drop the first period, which is NaN by construction for differenced series
        t = t.iloc[1:] if len(t) else t
        out.append(apply_mask(t, cfg.mask) if mask else t)
    return out[0], out[1]


def standardize(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    mean, std = df.mean(), df.std()
    return (df - mean) / std, mean, std


def annualize(q_growth_pct):
    """q/q % (log) growth -> annualized % rate: 100 * (exp(4 g / 100) - 1)."""
    return 100 * (np.exp(4 * np.asarray(q_growth_pct, dtype=float) / 100) - 1)


def summary(monthly: pd.DataFrame, quarterly: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    rows = []
    for frame in (monthly, quarterly):
        for k in frame:
            col = frame[k].dropna()
            s: Series = cfg.get(k)
            rows.append({
                "key": k, "freq": s.freq, "transform": s.transform,
                "first": str(col.index.min()) if len(col) else "",
                "last": str(col.index.max()) if len(col) else "",
                "n": len(col),
                "mean": round(col.mean(), 3) if len(col) else np.nan,
                "std": round(col.std(), 3) if len(col) else np.nan,
            })
    return pd.DataFrame(rows).set_index("key")
