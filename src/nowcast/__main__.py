"""Command line entry point.

    python -m nowcast fetch [--vintage YYYY-MM-DD]   # pull everything, save a dated snapshot
    python -m nowcast panel [--vintage latest]       # summarize the transformed panel
    python -m nowcast nowcast [--vintage latest]     # fit, print nowcast + news (records nothing)
    python -m nowcast update [--vintage latest]      # same, and append to output/*.csv
    python -m nowcast report                         # build site/index.html
    python -m nowcast backtest --name base [--blocks global,real,output]

The weekly job runs fetch, update, report.
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from . import model as M
from .config import load_config
from .fetch import fetch_all, load_snapshot, save_snapshot
from .transform import build_panel, summary


def _cfg(args):
    return load_config(args.config) if args.config else load_config()


def _spec(args) -> M.Spec:
    return M.Spec(blocks=tuple(args.blocks.split(",")), factor_order=args.factor_order)


def cmd_fetch(args) -> int:
    cfg = _cfg(args)
    raw, status = fetch_all(cfg)
    out = save_snapshot(raw, status, cfg, vintage=args.vintage)
    print(f"snapshot written to {out}")
    if raw[raw["key"] == cfg.target].empty:
        print(f"ERROR: target series {cfg.target!r} missing from snapshot", file=sys.stderr)
        return 1
    failed = {k: v for k, v in status.items() if v != "ok"}
    if failed:
        print(f"WARNING: sources failed: {failed}", file=sys.stderr)
    return 0


def cmd_panel(args) -> int:
    cfg = _cfg(args)
    raw = load_snapshot(args.vintage)
    monthly, quarterly = build_panel(raw, cfg)
    with pd.option_context("display.width", 140, "display.max_rows", 100):
        print(f"vintage {raw.attrs['vintage']}")
        print(summary(monthly, quarterly, cfg))
    return 0


def _weekly(args, record: bool) -> int:
    from .pipeline import weekly
    r = weekly(args.vintage, _spec(args), _cfg(args), record=record)
    print(f"vintage {r['vintage']}  (annualized %, q/q real GDP)")
    print(r["nowcast"].round(2))
    if not r["news"]:
        print("\nno earlier snapshot: news decomposition starts next week")
    for q, n in r["news"].items():
        print(f"\nnews for {q} since {r['previous']}: {n.attrs['prev']:.2f} -> {n.attrs['post']:.2f}")
        print(n[["name", "impact_ann"]].round(3).to_string(index=False))
    return 0


def cmd_nowcast(args) -> int:
    return _weekly(args, record=False)


def cmd_update(args) -> int:
    return _weekly(args, record=True)


def cmd_report(args) -> int:
    from .report import build
    print(f"page written to {build()}")
    return 0


def cmd_backtest(args) -> int:
    from . import backtest as B
    cfg = _cfg(args)
    raw = load_snapshot(args.vintage)
    pred = B.run(raw, cfg, _spec(args), start=args.start, end=args.end)
    path = B.save(pred, args.name)
    print(path.read_text(encoding="utf-8"))
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="nowcast")
    p.add_argument("--config", help="path to series.yaml (default: config/series.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="fetch all series and save a dated snapshot")
    f.add_argument("--vintage", help="snapshot date label (default: today)")
    f.set_defaults(func=cmd_fetch)
    t = sub.add_parser("panel", help="summarize the transformed panel for a snapshot")
    t.add_argument("--vintage", default="latest")
    t.set_defaults(func=cmd_panel)
    r = sub.add_parser("report", help="build the static page in site/")
    r.set_defaults(func=cmd_report)
    for name, func, helptext in (("nowcast", cmd_nowcast, "fit the model and print the nowcast"),
                                 ("update", cmd_update, "nowcast and append to the live record"),
                                 ("backtest", cmd_backtest, "pseudo-real-time backtest")):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("--vintage", default="latest")
        c.add_argument("--blocks", default=",".join(M.Spec().blocks))
        c.add_argument("--factor-order", type=int, default=1)
        if name == "backtest":
            c.add_argument("--name", default="output_block")
            c.add_argument("--start", default="2010-01-01")
            c.add_argument("--end", default=None)
        c.set_defaults(func=func)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
