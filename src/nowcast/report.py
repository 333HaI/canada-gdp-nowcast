"""Builds site/index.html from output/. Data is inlined as JSON, charts are Plotly.js."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as B
from . import history as H
from .config import ROOT

SITE = ROOT / "site"
BACKTEST_RUN = "output_block"
PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"


def repo_url() -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        return f"https://github.com/{repo}"
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url.removesuffix(".git") or None


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", double_precision=4))


def backtest_data(out: Path = H.OUT) -> dict | None:
    path = B.OUT_DIR / f"predictions_{BACKTEST_RUN}.csv"
    if not path.exists():
        return None
    pred = pd.read_csv(path)
    # last nowcast made inside each quarter
    eoq = (pred[pred["month"] == 3].sort_values("vintage")
           .groupby("target").last().reset_index())
    path_df = eoq[["target", "actual", "model", "ar1", "naive", "covid"]]
    t = B.score(pred)
    rmse = t.drop(index="all horizons")[["model", "ar1", "naive", "n"]].reset_index(names="horizon")
    overall = t.loc["all horizons"]
    s_ar, p_ar = B.dm_test(pred, "ar1")
    s_nv, p_nv = B.dm_test(pred, "naive")
    cov = B.coverage(pred)
    return {
        "path": _records(path_df),
        "rmse": _records(rmse),
        "overall": {k: float(overall[k]) for k in ("model", "ar1", "naive")} | {"n": int(overall["n"])},
        "dm": {"ar1": p_ar, "naive": p_nv},
        "coverage": {"68": float(cov["68%"]), "90": float(cov["90%"])},
        "start": str(pred["target"].min()), "end": str(pred["target"].max()),
    }


def page_data(out: Path = H.OUT) -> dict:
    latest_path = out / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else None
    hist = H.read(H.HISTORY, out)
    first = H.read(H.FIRST, out)
    return {
        "latest": latest,
        "history": _records(hist[["vintage", "quarter", "nowcast", "lo68", "hi68", "lo90", "hi90"]])
        if len(hist) else [],
        "first": _records(first) if len(first) else [],
        "live": _records(H.live_rmse(out)),
        "backtest": backtest_data(out),
        "repo": repo_url(),
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def pages_url() -> str | None:
    url = repo_url()
    if not url or "github.com/" not in url:
        return None
    owner, repo = url.split("github.com/", 1)[1].split("/")[:2]
    return f"https://{owner.lower()}.github.io/{repo}/"


def readme_block(data: dict) -> str:
    L, bt = data["latest"], data["backtest"]
    parts = [f"{q['quarter']} {q['nowcast']:.1f}% (68%: {q['lo68']:.1f} to {q['hi68']:.1f})"
             for q in L["nowcast"]]
    lines = [f"Nowcast as of {L['vintage']}: " + ", ".join(parts) + "."]
    if bt:
        o = bt["overall"]
        lines += ["", f"Backtest {bt['start'][:4]}-{bt['end'][:4]} (excl. 2020Q1-2021Q1): RMSE "
                  f"{o['model']:.2f} vs {o['ar1']:.2f} for an AR(1) and {o['naive']:.2f} for a naive "
                  f"monthly GDP tracker."]
    url = pages_url()
    if url:
        lines += ["", f"Live: {url}"]
    return "\n".join(lines)


def update_readme(data: dict, path: Path = ROOT / "README.md") -> bool:
    """Replace the text between the nowcast:start/end markers."""
    text = path.read_text(encoding="utf-8")
    start, end = "<!-- nowcast:start", "<!-- nowcast:end -->"
    if start not in text or end not in text:
        return False
    head, rest = text.split(start, 1)
    marker_line, _ = rest.split("\n", 1)
    _, tail = rest.split(end, 1)
    new = f"{head}{start}{marker_line}\n{readme_block(data)}\n{end}{tail}"
    if new != text:
        path.write_text(new, encoding="utf-8")
    return new != text


def build(out: Path = H.OUT, site: Path = SITE, readme: bool = True) -> Path:
    data = page_data(out)
    if data["latest"] is None:
        raise FileNotFoundError("output/latest.json missing: run `python -m nowcast update` first")
    html = TEMPLATE.replace("__PLOTLY__", PLOTLY).replace(
        "__DATA__", json.dumps(data, default=float).replace("</", "<\\/"))
    site.mkdir(parents=True, exist_ok=True)
    path = site / "index.html"
    path.write_text(html, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    if readme:
        update_readme(data)
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canada GDP Nowcast</title>
<meta name="description" content="Weekly nowcast of Canadian real GDP growth.">
<link rel="icon" href="data:,">
<style>
:root { color-scheme: light; --bg: #fff; --fg: #111; --dim: #777; --rule: #e4e4e4;
  --line2: #a8a8a8; --band1: rgba(17,17,17,.12); --band2: rgba(17,17,17,.05); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { color-scheme: dark; --bg: #0f0f0f; --fg: #e4e4e4; --dim: #8a8a8a;
    --rule: #262626; --line2: #5c5c5c; --band1: rgba(228,228,228,.16); --band2: rgba(228,228,228,.07); }
}
:root[data-theme="dark"] { color-scheme: dark; --bg: #0f0f0f; --fg: #e4e4e4; --dim: #8a8a8a;
  --rule: #262626; --line2: #5c5c5c; --band1: rgba(228,228,228,.16); --band2: rgba(228,228,228,.07); }
html { background: var(--bg); }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
main { max-width: 780px; margin: 0 auto; padding: 28px 16px 48px; }
h1 { font-size: 15px; margin: 0; font-weight: 700; }
h2 { font-size: 13px; margin: 28px 0 6px; font-weight: 700; }
p { margin: 4px 0; }
.dim { color: var(--dim); }
a { color: inherit; }
table { border-collapse: collapse; font-variant-numeric: tabular-nums; }
td, th { padding: 2px 20px 2px 0; text-align: right; white-space: nowrap; font-weight: 400; }
td:first-child, th:first-child { text-align: left; }
th { color: var(--dim); }
.big td:nth-child(2) { font-weight: 700; }
.big td:last-child { text-align: left; }
.scroll { overflow-x: auto; }
.pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px 24px; }
.chart { width: 100%; height: 190px; }
.k { display: inline-block; width: 14px; border-top: 2px solid; vertical-align: middle; margin-right: 4px; }
ul { margin: 4px 0; padding-left: 18px; }
footer { margin-top: 32px; color: var(--dim); }
</style>
</head>
<body>
<main>
<h1>canadian gdp nowcast</h1>
<p class="dim">real GDP (expenditure), q/q at annual rate. re-estimated every friday.</p>
<p class="dim" id="meta"></p>

<h2>now</h2>
<div class="scroll"><table class="big" id="now"></table></div>

<h2>track</h2>
<div class="pair" id="tracks"></div>

<h2 id="news-h">news</h2>
<div class="pair" id="news"></div>

<h2>live record</h2>
<div id="live"></div>

<div id="bt">
<h2 id="bt-h">backtest</h2>
<p id="bt-line"></p>
<div class="scroll"><table id="bt-table"></table></div>
<p style="margin-top:12px"><span class="k" style="border-color:var(--fg)"></span>nowcast at end of quarter
  &nbsp; <span class="k" style="border-color:var(--line2)"></span>published</p>
<div class="chart" id="bt-path" style="height:220px"></div>
</div>

<h2>notes</h2>
<ul class="dim">
  <li>DynamicFactorMQ (statsmodels), 20 monthly series from StatCan, BoC and FRED, three factor blocks.</li>
  <li>backtest is pseudo real-time: today's data, release lags simulated, no revisions.</li>
  <li>Mar-Dec 2020 masked when estimating. bands leave out parameter uncertainty.</li>
  <li>live nowcasts are never edited and get scored against StatCan's first release.</li>
</ul>

<footer id="footer"></footer>
</main>

<script id="data" type="application/json">__DATA__</script>
<script src="__PLOTLY__"></script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const v = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const f = (x, d = 1) => x == null || isNaN(x) ? "-" : x.toFixed(d);
const sgn = (x, d = 2) => x == null || isNaN(x) ? "-" : (x > 0 ? "+" : "") + x.toFixed(d);
const $ = id => document.getElementById(id);
const row = (cells, tag = "td") => "<tr>" + cells.map(c => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
const qd = q => `${q.slice(0, 4)}-${String(3 * +q.slice(5) - 1).padStart(2, "0")}-15`;
const L = D.latest, B = D.backtest;

function text() {
  $("meta").textContent = `data as of ${L.vintage}. built ${D.built}.`;
  const n = L.nowcast.length;
  $("now").innerHTML = row(["quarter", "nowcast", "68%", "90%", "1w chg", ""], "th") + L.nowcast.map((r, i) => {
    const nw = L.news[r.quarter];
    return row([r.quarter, f(r.nowcast) + "%", `${f(r.lo68)} to ${f(r.hi68)}`, `${f(r.lo90)} to ${f(r.hi90)}`,
      nw ? sgn(nw.post - nw.prev) : "-", `<span class="dim">${i === n - 1 ? "current" : "not yet published"}</span>`]);
  }).join("");

  if (D.live.length) {
    $("live").innerHTML = `<div class="scroll"><table>` +
      row(["quarter", "first release", "last nowcast", "error", "weeks", "rmse"], "th") +
      D.live.map(r => row([r.quarter, f(r.first_release), f(r.last_nowcast), sgn(r.last_nowcast - r.first_release),
        r.weeks, f(r.rmse, 2)])).join("") + "</table></div>";
  } else {
    $("live").innerHTML = `<p class="dim">nothing scored yet. first one when StatCan publishes ${L.nowcast[0].quarter}.</p>`;
  }

  if (B) {
    $("bt-h").textContent = `backtest ${B.start}-${B.end}, excl. 2020Q1-2021Q1`;
    const o = B.overall;
    $("bt-line").textContent = `rmse ${f(o.model, 2)} vs ${f(o.ar1, 2)} ar(1), ${f(o.naive, 2)} naive.  ` +
      `bands hit ${Math.round(100 * B.coverage["68"])}% / ${Math.round(100 * B.coverage["90"])}%.  n=${o.n}`;
    $("bt-table").innerHTML = row(["made in", "model", "ar(1)", "naive", "n"], "th") +
      B.rmse.map(r => row([r.horizon.replace("after Q end, ", "after q end, "), f(r.model, 2), f(r.ar1, 2), f(r.naive, 2), r.n])).join("");
  } else $("bt").style.display = "none";

  $("footer").innerHTML = "data: Statistics Canada, Bank of Canada, FRED. not an official forecast." +
    (D.repo ? ` <a href="${D.repo}">source</a>` : "");
}

function base(extra = {}) {
  const ax = { showgrid: false, zeroline: false, showline: true, linecolor: v("--rule"), ticks: "outside",
    tickcolor: v("--rule"), ticklen: 3, tickfont: { color: v("--dim"), size: 11 }, fixedrange: true, automargin: true };
  return Object.assign({ paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", showlegend: false,
    font: { family: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", size: 11, color: v("--dim") },
    margin: { l: 4, r: 8, t: 8, b: 4 }, hovermode: "closest",
    hoverlabel: { bgcolor: v("--bg"), bordercolor: v("--rule"), font: { family: "ui-monospace, monospace", color: v("--fg") } },
    xaxis: Object.assign({}, ax, extra.xaxis), yaxis: Object.assign({}, ax, extra.yaxis) },
    Object.fromEntries(Object.entries(extra).filter(([k]) => k !== "xaxis" && k !== "yaxis")));
}
const CFG = { displayModeBar: false, responsive: true };

function tracks() {
  const box = $("tracks"); box.innerHTML = "";
  const qs = [...new Set([...D.history.map(r => r.quarter), ...L.nowcast.map(r => r.quarter)])].sort().slice(-2);
  qs.forEach(q => {
    const h = D.history.filter(r => r.quarter === q).sort((a, b) => a.vintage < b.vintage ? -1 : 1);
    const wrap = document.createElement("div");
    wrap.innerHTML = `<p>${q} <span class="dim">${h.length} week${h.length === 1 ? "" : "s"}</span></p>`;
    const div = document.createElement("div"); div.className = "chart";
    wrap.append(div); box.append(wrap);
    const x = h.map(r => r.vintage), y = h.map(r => r.nowcast);
    const area = (lo, hi, c) => [{ x, y: h.map(r => r[hi]), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x, y: h.map(r => r[lo]), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: c, hoverinfo: "skip" }];
    const bar = (lo, hi, w, c) => ({ x, y, mode: "markers", marker: { size: 1, color: "rgba(0,0,0,0)" }, hoverinfo: "skip",
      error_y: { type: "data", symmetric: false, array: h.map(r => r[hi] - r.nowcast),
        arrayminus: h.map(r => r.nowcast - r[lo]), thickness: w, width: 0, color: c } });
    const bands = h.length >= 3 ? [...area("lo90", "hi90", v("--band2")), ...area("lo68", "hi68", v("--band1"))]
      : [bar("lo90", "hi90", 1, v("--line2")), bar("lo68", "hi68", 5, v("--line2"))];
    const tr = [...bands, { x, y, mode: "lines+markers", line: { color: v("--fg"), width: 1.5 },
      marker: { size: 5, color: v("--fg") }, customdata: h.map(r => [r.lo68, r.hi68]),
      hovertemplate: "%{x}<br>%{y:.1f}%  (68%: %{customdata[0]:.1f} to %{customdata[1]:.1f})<extra></extra>" }];
    const fr = D.first.find(r => r.quarter === q);
    if (fr) tr.push({ x: [fr.seen_in_vintage], y: [fr.first_release], mode: "markers+text", text: ["first release"],
      textposition: "middle left", textfont: { color: v("--dim"), size: 11 },
      marker: { symbol: "x-thin", size: 9, line: { width: 1.5, color: v("--fg") } }, hovertemplate: "first release %{y:.1f}%<extra></extra>" });
    const t0 = new Date(x[0] || L.vintage).getTime();
    const xr = h.length > 1 ? undefined : [new Date(t0 - 30 * 864e5), new Date(t0 + 30 * 864e5)];
    Plotly.react(div, tr, base({ xaxis: { type: "date", range: xr, tickformat: "%b %d" }, yaxis: { ticksuffix: "%" } }), CFG);
  });
}

function news() {
  const box = $("news"); box.innerHTML = "";
  const qs = Object.keys(L.news);
  if (!qs.length) {
    box.innerHTML = `<p class="dim">needs two weekly runs. starts next friday.</p>`; return;
  }
  $("news-h").textContent = `news since ${L.previous_vintage} (pp)`;
  qs.forEach(q => {
    const n = L.news[q], items = n.items.filter(r => Math.abs(r.impact_ann) >= 0.005).slice(0, 8);
    const w = document.createElement("div");
    w.innerHTML = `<p>${q}: ${f(n.prev, 2)} -> ${f(n.post, 2)}</p>` + (items.length
      ? `<table>${items.map(r => row([r.name, sgn(r.impact_ann)])).join("")}</table>`
      : `<p class="dim">nothing moved it by 0.01 or more</p>`);
    box.append(w);
  });
}

function backtest() {
  if (!B) return;
  const p = B.path, x = p.map(r => qd(r.target));
  Plotly.react("bt-path", [
    { x, y: p.map(r => r.actual), mode: "lines", line: { color: v("--line2"), width: 1.5 },
      customdata: p.map(r => r.target), hovertemplate: "%{customdata}  published %{y:.1f}%<extra></extra>" },
    { x, y: p.map(r => r.model), mode: "lines", line: { color: v("--fg"), width: 1.5 },
      hovertemplate: "nowcast %{y:.1f}%<extra></extra>" }],
    base({ hovermode: "x", yaxis: { range: [-6, 9], ticksuffix: "%" }, xaxis: { type: "date" },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: v("--rule"), width: 1 } }],
      annotations: [{ x: "2020-08-15", y: 1, yref: "paper", yanchor: "top", showarrow: false,
        text: "2020: off scale", font: { size: 10, color: v("--dim") } }] }), CFG);
}

const draw = () => { if (window.Plotly) { tracks(); backtest(); } };
text(); news(); draw();
if (!window.Plotly) document.querySelectorAll(".chart").forEach(c => c.outerHTML = `<p class="dim">charts didn't load</p>`);
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", draw);
new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
</script>
</body>
</html>
"""
