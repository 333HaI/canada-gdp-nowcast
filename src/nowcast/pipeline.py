"""One weekly update: fit on the latest snapshot, nowcast, news, and record.

Called by `python -m nowcast update` (records) and `python -m nowcast nowcast`
(prints only).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from . import history as H
from . import model as M
from .config import Config, load_config
from .fetch import VINTAGE_DIR, load_snapshot
from .transform import build_panel

log = logging.getLogger(__name__)


def previous_vintage(vintage: str, root: Path = VINTAGE_DIR) -> str | None:
    earlier = sorted(p.name for p in root.iterdir() if (p / "raw.csv").exists() and p.name < vintage)
    return earlier[-1] if earlier else None


def weekly(vintage: str = "latest", spec: M.Spec = M.Spec(), cfg: Config | None = None,
           record: bool = False, root: Path = VINTAGE_DIR, out: Path = H.OUT) -> dict:
    cfg = cfg or load_config()
    raw = load_snapshot(vintage, root=root)
    vintage = raw.attrs["vintage"]
    monthly, quarterly = build_panel(raw, cfg)
    quarters = M.open_quarters(quarterly, cfg.target, pd.Timestamp(vintage))
    mm, qq = M.prepare(monthly, quarterly, cfg, quarters[-1].asfreq("M", how="end"))
    res = M.fit(mm, qq, cfg, spec)
    nc = M.nowcast(res, quarters, cfg.target)

    news, prev = {}, previous_vintage(vintage, root)
    if prev is not None:
        pm, pq = build_panel(load_snapshot(prev, root=root), cfg)
        pm, pq = M.prepare(pm, pq, cfg, mm.index[-1])
        res_prev = M.refilter(res, pm.reindex(index=mm.index, columns=mm.columns),
                              pq.reindex(index=qq.index, columns=qq.columns))
        for q in quarters:
            news[str(q)] = M.news(res, res_prev, q, cfg.target, cfg)

    if record:
        spec_tag = "+".join(spec.blocks)
        n = H.record_nowcast(vintage, nc, spec_tag, out)
        for q, df in news.items():
            H.record_news(vintage, prev, q, df, out)
        _, q_unmasked = build_panel(raw, cfg, mask=False)
        f = H.record_first_releases(vintage, q_unmasked[cfg.target], out)
        log.info("recorded %d nowcast row(s), %d first release(s)", n, f)
        write_latest(vintage, prev, nc, news, out)
    return {"vintage": vintage, "previous": prev, "nowcast": nc, "news": news}


def write_latest(vintage, prev, nc, news, out: Path = H.OUT) -> Path:
    """Current state for the web page (overwritten weekly; history is in the CSVs)."""
    payload = {
        "vintage": vintage,
        "previous_vintage": prev,
        "nowcast": nc.reset_index().to_dict("records"),
        "news": {q: {"prev": df.attrs.get("prev"), "post": df.attrs.get("post"),
                     "items": df.drop(columns=[c for c in ("impact_qoq",) if c in df])
                                .to_dict("records")}
                 for q, df in news.items()},
    }
    path = out / "latest.json"
    path.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    return path
