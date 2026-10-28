"""Monthly GDP advance estimates ("flash"), scraped from The Daily.

They aren't in WDS. Every "Gross domestic product by industry" release has a
line like "Advance information indicates that real GDP increased 0.3% in
September" and a link to the previous release. update() finds the newest
release and walks back until it reaches one that's already in the CSV.

Two rows were typed in by hand: March 2020 (a separate flash notice on
2020-04-15) and May 2022 (that release went out as an Analysis in Brief).
"""
from __future__ import annotations

import html
import logging
import re
import time

import pandas as pd
import requests

from .config import ROOT
from .fetch import STATCAN_URL, TIMEOUT, session

log = logging.getLogger(__name__)

CSV = ROOT / "data" / "manual" / "gdp_flash.csv"
DAILY = "https://www150.statcan.gc.ca/n1/daily-quotidien/"
GDP_TABLE = 36100434
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
TITLE = re.compile(r"Gross domestic product by industry, [A-Z][a-z]+ \d{4}")
LEAD = re.compile(r"(?i)(advanced?|preliminary) information indicates")
UP = re.compile(r"(?i)\b(increas\w*|rose|up|expan\w*|rebound\w*|grew|gain\w*)\b")
DOWN = re.compile(r"(?i)\b(decreas\w*|declin\w*|down|fell|contract\w*|drop\w*)\b")


def _text(page: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", page)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def _url(name: str) -> str:
    # name like 241031a
    return f"{DAILY}{name[:6]}/dq{name}-eng.htm"


def parse(page: str) -> dict:
    """Release date, previous release, and the flash month + % m/m (None if there isn't one)."""
    text = _text(page)
    released = re.search(r"Released: ?(\d{4}-\d{2}-\d{2})", text).group(1)
    prev = re.search(r'href="[^"]*dq(\d{6}[a-z])-eng\.htm"[^>]*>\s*Previous release', page)
    out = {"released": released, "previous": _url(prev.group(1)) if prev else None,
           "date": None, "value": None}
    m = LEAD.search(text)
    if not m:
        return out
    # the sentence, up to a full stop that isn't a decimal point
    s = re.split(r"\.(?!\d)", text[m.start():m.start() + 300], maxsplit=1)[0]
    # first month named, the sentence can go on about the month before
    named = re.search(r"\b(" + "|".join(MONTHS) + r")\b", s)
    if named is None:
        raise ValueError(f"no month in {s!r}")
    month = MONTHS.index(named.group(1)) + 1
    pct = re.search(r"(\d+(?:\.\d+)?) ?%", s)
    up, down = UP.search(s), DOWN.search(s)
    if "unchanged" in s:
        value = 0.0
    elif pct and (up or down):
        first_up = up and (not down or up.start() < down.start())
        value = float(pct.group(1)) * (1 if first_up else -1)
    else:
        raise ValueError(f"can't read the advance estimate in {s!r}")
    rel = pd.Timestamp(released)
    year = rel.year if month <= rel.month else rel.year - 1
    out.update(date=f"{year}-{month:02d}-01", value=value)
    return out


def newest(http: requests.Session) -> str:
    """URL of the latest GDP by industry release, found via the table's release time."""
    r = http.post(STATCAN_URL + "getCubeMetadata", json=[{"productId": GDP_TABLE}], timeout=TIMEOUT)
    r.raise_for_status()
    day = pd.Timestamp(r.json()[0]["object"]["releaseTime"]).strftime("%y%m%d")
    for letter in "abcdefghijkl":
        resp = http.get(_url(day + letter), timeout=TIMEOUT)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        title = re.search(r"<title>(.*?)</title>", resp.text, re.S)
        if title and TITLE.search(_text(title.group(1))):
            return _url(day + letter)
    raise RuntimeError(f"no GDP by industry release in The Daily on {day}")


def update(path=CSV, since: str = "2020-01-01", http: requests.Session | None = None,
           pause: float = 1.0) -> pd.DataFrame:
    """Append flash estimates from releases not in the CSV yet. Returns the new rows.

    Existing rows are never changed.
    """
    http = http or session()
    old = pd.read_csv(path, dtype=str)
    known = set(old["release_date"])
    rows, url = [], newest(http)
    while url:
        r = http.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        p = parse(r.text)
        if p["released"] in known or p["released"] < since:
            break
        if p["date"] is None:
            log.warning("no advance estimate in %s", url)
        else:
            rows.append({"date": p["date"], "value": p["value"], "release_date": p["released"]})
        url = p["previous"]
        time.sleep(pause)
    new = pd.DataFrame(rows, columns=["date", "value", "release_date"])
    new = new[~new["date"].isin(old["date"])].sort_values("date")
    if len(new):
        both = pd.concat([old, new.astype(str)], ignore_index=True).sort_values("date")
        both.to_csv(path, index=False)
    return new.reset_index(drop=True)
