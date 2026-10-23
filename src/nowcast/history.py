"""Live record, append-only CSVs in output/.

nowcast_history.csv  vintage x quarter
news_history.csv     vintage x quarter x series
first_releases.csv   quarter -> StatCan's first published value

Existing keys are skipped, never overwritten.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT
from .transform import annualize

log = logging.getLogger(__name__)

OUT = ROOT / "output"
HISTORY = "nowcast_history.csv"
NEWS = "news_history.csv"
FIRST = "first_releases.csv"

HISTORY_COLS = ["vintage", "quarter", "nowcast", "lo68", "hi68", "lo90", "hi90",
                "qoq", "sd_qoq", "spec", "run_at"]
NEWS_COLS = ["vintage", "quarter", "previous_vintage", "series", "name", "impact_ann", "impact_qoq"]
FIRST_COLS = ["quarter", "first_release", "first_release_qoq", "seen_in_vintage"]
KEYS = {HISTORY: ["vintage", "quarter"], NEWS: ["vintage", "quarter", "series"], FIRST: ["quarter"]}


def read(name: str, out: Path = OUT) -> pd.DataFrame:
    cols = {HISTORY: HISTORY_COLS, NEWS: NEWS_COLS, FIRST: FIRST_COLS}[name]
    path = out / name
    if not path.exists():
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path, dtype={"vintage": str, "quarter": str, "previous_vintage": str,
                                    "seen_in_vintage": str})


def append(name: str, rows: pd.DataFrame, out: Path = OUT) -> int:
    """Append rows with new keys, skip the rest."""
    if rows.empty:
        return 0
    cols = {HISTORY: HISTORY_COLS, NEWS: NEWS_COLS, FIRST: FIRST_COLS}[name]
    rows = rows[cols].astype({k: str for k in KEYS[name]})
    old = read(name, out)
    if len(old):
        seen = set(map(tuple, old[KEYS[name]].astype(str).to_numpy()))
        new_mask = [tuple(r) not in seen for r in rows[KEYS[name]].to_numpy()]
        skipped = len(rows) - sum(new_mask)
        if skipped:
            log.warning("%s: %d row(s) already recorded, left unchanged", name, skipped)
        rows = rows[new_mask]
    if rows.empty:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    rows.to_csv(path, mode="a", header=not path.exists(), index=False, float_format="%.4f")
    return len(rows)


def record_nowcast(vintage: str, nc: pd.DataFrame, spec: str, out: Path = OUT) -> int:
    rows = nc.reset_index().assign(
        vintage=vintage, spec=spec,
        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return append(HISTORY, rows, out)


def record_news(vintage: str, previous: str, quarter, news: pd.DataFrame, out: Path = OUT) -> int:
    rows = news.assign(vintage=vintage, quarter=str(quarter), previous_vintage=previous)
    if "name" not in rows:
        rows["name"] = rows["series"]
    return append(NEWS, rows, out)


def record_first_releases(vintage: str, target_qoq: pd.Series, out: Path = OUT) -> int:
    """Record first releases, but only for quarters we actually nowcast.

    Anything published before launch is already revised in the snapshot.
    """
    nowcast_q = set(read(HISTORY, out)["quarter"])
    done = set(read(FIRST, out)["quarter"])
    rows = []
    for q, v in target_qoq.dropna().items():
        if str(q) in nowcast_q and str(q) not in done:
            rows.append({"quarter": str(q), "first_release": float(annualize(v)),
                         "first_release_qoq": float(v), "seen_in_vintage": vintage})
    return append(FIRST, pd.DataFrame(rows, columns=FIRST_COLS), out)


def scorecard(out: Path = OUT) -> pd.DataFrame:
    """History joined to first releases."""
    h, f = read(HISTORY, out), read(FIRST, out)
    if h.empty:
        return h.assign(first_release=pd.Series(dtype=float), error=pd.Series(dtype=float))
    s = h.merge(f[["quarter", "first_release"]], on="quarter", how="left")
    s["error"] = s["nowcast"] - s["first_release"]
    return s


def live_rmse(out: Path = OUT) -> pd.DataFrame:
    """Per released quarter: last nowcast and RMSE over its weeks."""
    s = scorecard(out).dropna(subset=["first_release"])
    if s.empty:
        return pd.DataFrame(columns=["quarter", "first_release", "last_nowcast", "weeks", "rmse"])
    g = s.sort_values("vintage").groupby("quarter")
    return pd.DataFrame({
        "first_release": g["first_release"].first(),
        "last_nowcast": g["nowcast"].last(),
        "weeks": g.size(),
        "rmse": g["error"].apply(lambda e: float(np.sqrt(np.mean(e ** 2)))),
    }).reset_index()
