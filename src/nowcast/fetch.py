"""Data clients: StatCan WDS, BoC Valet, FRED, plus hand-entered CSVs.

All of them return long rows: key, source_id, date, value, release_time.
date is the start of the reference period. release_time only exists for
StatCan and is the latest release/revision time, not the first release.
Daily series get averaged to months here.
"""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ROOT, Config, Series

log = logging.getLogger(__name__)

STATCAN_URL = "https://www150.statcan.gc.ca/t1/wds/rest/"
BOC_URL = "https://www.bankofcanada.ca/valet/"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

COLUMNS = ["key", "source_id", "date", "value", "release_time"]
TIMEOUT = 120


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "canada-gdp-nowcast (github.com; research)"
    return s


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def fetch_statcan(series: list[Series], start: str, http: requests.Session) -> pd.DataFrame:
    # WDS takes a comma-separated list, so one request covers everything
    owner = {vid: s.key for s in series for vid in s.ids}
    if not owner:
        return _frame([])
    resp = http.get(
        STATCAN_URL + "getDataFromVectorByReferencePeriodRange",
        params={
            "vectorIds": ",".join(owner),
            "startRefPeriod": start,
            "endReferencePeriod": date.today().replace(month=12, day=31).isoformat(),
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows, seen = [], set()
    for item in resp.json():
        if item.get("status") != "SUCCESS":
            log.warning("StatCan returned %s", item)
            continue
        obj = item["object"]
        vid = str(obj["vectorId"])
        seen.add(vid)
        for p in obj["vectorDataPoint"]:
            rows.append({"key": owner[vid], "source_id": vid, "date": p["refPer"],
                         "value": p["value"], "release_time": p.get("releaseTime")})
    missing = set(owner) - seen
    if missing:
        raise RuntimeError(f"StatCan vectors not returned: {sorted(missing)}")
    return _frame(rows)


def fetch_boc(series: list[Series], start: str, http: requests.Session) -> pd.DataFrame:
    if not series:
        return _frame([])
    names = [s.ids[0] for s in series]
    resp = http.get(BOC_URL + f"observations/{','.join(names)}/json",
                    params={"start_date": start}, timeout=TIMEOUT)
    resp.raise_for_status()
    obs = resp.json()["observations"]
    frames = []
    for s in series:
        name = s.ids[0]
        pts = [(o["d"], o[name]["v"]) for o in obs if name in o and o[name].get("v") not in (None, "")]
        if not pts:
            raise RuntimeError(f"BoC series {name} returned no observations")
        ser = pd.Series([float(v) for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))
        if s.native_freq == "D":
            ser = ser.resample("MS").mean()
        else:
            ser.index = ser.index.to_period("M").to_timestamp()
        frames.append(pd.DataFrame({"key": s.key, "source_id": name, "date": ser.index,
                                    "value": ser.values, "release_time": None}))
    return _frame([]) if not frames else pd.concat(frames, ignore_index=True)[COLUMNS]


def fetch_fred(series: list[Series], start: str, http: requests.Session) -> pd.DataFrame:
    # API if FRED_API_KEY is set, otherwise the public fredgraph CSV
    key = os.environ.get("FRED_API_KEY")
    frames = []
    for s in series:
        sid = s.ids[0]
        if key:
            resp = http.get(FRED_API_URL, params={"series_id": sid, "api_key": key,
                                                  "file_type": "json", "observation_start": start},
                            timeout=TIMEOUT)
            resp.raise_for_status()
            df = pd.DataFrame(resp.json()["observations"])[["date", "value"]]
        else:
            resp = http.get(FRED_CSV_URL, params={"id": sid, "cosd": start}, timeout=TIMEOUT)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"].replace(".", None), errors="coerce")
        df = df[pd.to_datetime(df["date"]) >= pd.Timestamp(start)].dropna(subset=["value"])
        frames.append(df.assign(key=s.key, source_id=sid, release_time=None))
    if not frames:
        return _frame([])
    return _frame(pd.concat(frames, ignore_index=True)[COLUMNS].to_dict("records"))


def fetch_manual(series: list[Series]) -> pd.DataFrame:
    frames = []
    for s in series:
        path = ROOT / s.ids[0]
        df = pd.read_csv(path)
        if df.empty:
            log.info("%s: %s has no rows yet", s.key, path.name)
            continue
        frames.append(pd.DataFrame({"key": s.key, "source_id": s.ids[0], "date": df["date"],
                                    "value": df["value"], "release_time": df.get("release_date")}))
    if not frames:
        return _frame([])
    return _frame(pd.concat(frames, ignore_index=True).to_dict("records"))


def fetch_all(cfg: Config) -> tuple[pd.DataFrame, dict]:
    """Returns (raw rows, status per source).

    A source that fails is logged and marked in the status dict instead of
    raising. The CLI still exits non-zero if the target is missing.
    """
    http = session()
    jobs = {
        "statcan": lambda: fetch_statcan(cfg.by_source("statcan"), cfg.start, http),
        "boc": lambda: fetch_boc(cfg.by_source("boc"), cfg.start, http),
        "fred": lambda: fetch_fred(cfg.by_source("fred"), cfg.start, http),
        "manual": lambda: fetch_manual(cfg.by_source("manual")),
    }
    frames, status = [], {}
    for name, job in jobs.items():
        try:
            df = job()
            frames.append(df)
            status[name] = "ok"
            log.info("%s: %d rows", name, len(df))
        except Exception as exc:  # noqa: BLE001
            log.error("%s fetch failed: %s", name, exc)
            status[name] = f"failed: {exc}"
    raw = pd.concat(frames, ignore_index=True) if frames else _frame([])
    return raw.sort_values(["key", "source_id", "date"]).reset_index(drop=True), status


VINTAGE_DIR = ROOT / "data" / "vintages"


def save_snapshot(raw: pd.DataFrame, status: dict, cfg: Config,
                  vintage: str | None = None, root: Path = VINTAGE_DIR) -> Path:
    """data/vintages/YYYY-MM-DD/raw.csv + manifest.json. Same day overwrites."""
    vintage = vintage or date.today().isoformat()
    out = root / vintage
    out.mkdir(parents=True, exist_ok=True)
    raw.assign(date=raw["date"].dt.strftime("%Y-%m-%d")).to_csv(out / "raw.csv", index=False)

    per_series = {}
    for s in cfg.series:
        sub = raw[raw["key"] == s.key].dropna(subset=["value"])
        per_series[s.key] = {
            "source": s.source,
            "ids": list(s.ids),
            "n_obs": int(len(sub)),
            "first": sub["date"].min().strftime("%Y-%m-%d") if len(sub) else None,
            "last": sub["date"].max().strftime("%Y-%m-%d") if len(sub) else None,
        }
    manifest = {
        "vintage": vintage,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fred_mode": "api" if os.environ.get("FRED_API_KEY") else "public_csv",
        "sources": status,
        "series": per_series,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def load_snapshot(vintage: str = "latest", root: Path = VINTAGE_DIR) -> pd.DataFrame:
    if vintage == "latest":
        dirs = sorted(p for p in root.iterdir() if (p / "raw.csv").exists())
        if not dirs:
            raise FileNotFoundError(f"no snapshots under {root}")
        path = dirs[-1]
    else:
        path = root / vintage
    raw = pd.read_csv(path / "raw.csv", dtype={"source_id": str}, parse_dates=["date"])
    raw.attrs["vintage"] = path.name
    return raw
