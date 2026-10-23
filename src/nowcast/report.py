"""Build the static page (site/index.html) from the files under output/.

The page is one self-contained HTML file: the data are embedded as JSON and
the charts are drawn client-side with Plotly.js. Colors are CSS tokens (light
and dark), read by the chart code at render time, so charts follow the
reader's color scheme.
"""
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
    # one point per quarter: the nowcast from the last vintage inside the quarter
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


def _pct(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}%".replace("-", "−")


def readme_block(data: dict) -> str:
    L, bt = data["latest"], data["backtest"]
    parts = [f"{q['quarter']} **{_pct(q['nowcast'])}** (68% band {_pct(q['lo68'])[:-1]} to {_pct(q['hi68'])})"
             for q in L["nowcast"]]
    lines = [f"**Latest nowcast (data as of {L['vintage']}):** " + "; ".join(parts) + "."]
    if bt:
        o = bt["overall"]
        lines += ["", f"**Backtest:** {bt['start'][:4]}–{bt['end'][:4]}, excluding 2020Q1–2021Q1. "
                  f"RMSE is **{o['model']:.2f} pp**, against {o['ar1']:.2f} for an AR(1) "
                  f"({100 * (1 - o['model'] / o['ar1']):.0f}% lower) and {o['naive']:.2f} for a naive "
                  f"monthly-GDP tracker ({100 * (1 - o['model'] / o['naive']):.0f}% lower)."]
    url = pages_url()
    if url:
        lines += ["", f"**Live page:** {url}"]
    return "\n".join(lines)


def update_readme(data: dict, path: Path = ROOT / "README.md") -> bool:
    """Rewrite the block between the nowcast:start / nowcast:end markers."""
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
<meta name="description" content="Weekly nowcast of Canadian quarterly real GDP growth from a mixed-frequency dynamic factor model.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M2 12 L6 7 L9 9 L14 3' stroke='%232a78d6' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
:root {
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f4f3f0; --border: #e4e3de;
  --text-1: #0b0b0b; --text-2: #52514e; --text-3: #75746f;
  --grid: #e9e8e4; --band-68: rgba(42,120,214,0.16); --band-90: rgba(42,120,214,0.08);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --ink: #0b0b0b;
  --pos: #2a78d6; --neg: #e34948; --excluded: rgba(82,81,78,0.08);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #34342f;
    --text-1: #f0efec; --text-2: #c3c2b7; --text-3: #9a9990;
    --grid: #2e2e2b; --band-68: rgba(57,135,229,0.22); --band-90: rgba(57,135,229,0.11);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --ink: #f0efec;
    --pos: #3987e5; --neg: #e66767; --excluded: rgba(195,194,183,0.07);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #34342f;
  --text-1: #f0efec; --text-2: #c3c2b7; --text-3: #9a9990;
  --grid: #2e2e2b; --band-68: rgba(57,135,229,0.22); --band-90: rgba(57,135,229,0.11);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --ink: #f0efec;
  --pos: #3987e5; --neg: #e66767; --excluded: rgba(195,194,183,0.07);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text-1);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px; font-weight: 650; letter-spacing: -0.01em; }
h2 { font-size: 18px; margin: 0 0 4px; font-weight: 620; }
.sub { color: var(--text-2); margin: 0; }
.muted { color: var(--text-3); font-size: 13px; }
section { margin-top: 40px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 24px; }
.tile { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
.tile .label { color: var(--text-2); font-size: 14px; }
.tile .value { font-size: 44px; font-weight: 640; line-height: 1.1; margin: 6px 0 4px; font-variant-numeric: proportional-nums; }
.tile .bands { color: var(--text-2); font-size: 14px; }
.tile .delta { font-size: 13px; color: var(--text-3); margin-top: 6px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 12px; }
.card { border: 1px solid var(--border); border-radius: 10px; padding: 14px 14px 6px; min-width: 0; }
.card h3 { font-size: 14px; font-weight: 600; margin: 0 0 2px; }
.chart { width: 100%; min-height: 260px; }
.empty { color: var(--text-3); padding: 24px 4px; font-size: 14px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-2); font-weight: 560; }
.tablewrap { overflow-x: auto; margin-top: 8px; }
.legend { display: flex; flex-wrap: wrap; gap: 16px; color: var(--text-2); font-size: 13px; margin: 6px 0 0; }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; }
.key i.sq { width: 10px; height: 10px; border-radius: 3px; }
.headline { font-size: 15px; margin-top: 10px; }
ul { padding-left: 20px; margin: 8px 0; } li { margin: 4px 0; color: var(--text-2); }
a { color: var(--s1); }
footer { margin-top: 48px; color: var(--text-3); font-size: 13px; }
</style>
</head>
<body>
<main>
  <header>
    <h1>Canadian GDP nowcast</h1>
    <p class="sub">Real GDP growth, expenditure-based, quarter over quarter at an annualized rate.
      Updated every Friday.</p>
    <p class="muted" id="meta"></p>
  </header>

  <div class="tiles" id="tiles"></div>

  <section>
    <h2>How the nowcast has moved</h2>
    <p class="sub">One point per weekly update, with 68% and 90% bands. The diamond marks StatCan's first release.</p>
    <div class="grid2" id="tracks"></div>
  </section>

  <section>
    <h2>What moved it this week</h2>
    <p class="sub" id="news-sub">Contribution of each new data release to the change in the nowcast, percentage points.</p>
    <div class="grid2" id="news"></div>
  </section>

  <section>
    <h2>Live record</h2>
    <p class="sub">Every weekly nowcast is kept unedited and scored against StatCan's first release of that quarter.</p>
    <div id="live"></div>
  </section>

  <section id="bt">
    <h2>Backtest</h2>
    <p class="sub" id="bt-sub"></p>
    <p class="headline" id="bt-headline"></p>
    <div class="grid2">
      <div class="card">
        <h3>End-of-quarter nowcast vs published GDP</h3>
        <div class="legend"><span class="key"><i style="background:var(--ink)"></i>Published GDP</span>
          <span class="key"><i style="background:var(--s1)"></i>Model nowcast</span></div>
        <div class="chart" id="bt-path"></div>
      </div>
      <div class="card">
        <h3>Error by horizon (RMSE, pp)</h3>
        <div class="legend"><span class="key"><i class="sq" style="background:var(--s1)"></i>Model</span>
          <span class="key"><i class="sq" style="background:var(--s2)"></i>AR(1)</span>
          <span class="key"><i class="sq" style="background:var(--s3)"></i>Naive tracker</span></div>
        <div class="chart" id="bt-rmse"></div>
      </div>
    </div>
    <div class="tablewrap" id="bt-table"></div>
  </section>

  <section>
    <h2>Method and limitations</h2>
    <ul>
      <li>A mixed-frequency dynamic factor model (statsmodels <code>DynamicFactorMQ</code>, EM estimation)
        on 20 monthly indicators from Statistics Canada, the Bank of Canada and FRED, with global,
        real-activity and output factor blocks. Missing values and the ragged edge are handled by the Kalman smoother.</li>
      <li>The backtest is pseudo-real-time. It uses today's revised data, with each series' availability rebuilt from typical
        release lags, so data revisions are ignored. The live record above has no such caveat.</li>
      <li>March to December 2020 is masked in estimation, and 2020Q1 to 2021Q1 are excluded from the backtest scores.</li>
      <li>Bands come from the model's state uncertainty and exclude parameter uncertainty.</li>
    </ul>
  </section>

  <footer id="footer"></footer>
</main>

<script id="data" type="application/json">__DATA__</script>
<script src="__PLOTLY__"></script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const pct = (v, d = 1) => (v == null || isNaN(v)) ? "–" : (v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
const pp = (v, d = 2) => (v == null || isNaN(v)) ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const el = (tag, attrs = {}, html = "") => { const e = document.createElement(tag); Object.assign(e, attrs); e.innerHTML = html; return e; };
const qDate = q => { const [y, n] = [+q.slice(0, 4), +q.slice(5)]; return `${y}-${String(3 * n - 1).padStart(2, "0")}-15`; };
const qLabel = q => q.replace("Q", " Q");

function layout(extra = {}) {
  const axis = { gridcolor: css("--grid"), zerolinecolor: css("--border"), linecolor: css("--border"),
    tickfont: { color: css("--text-3"), size: 12 }, automargin: true, fixedrange: true };
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: css("--text-2"), size: 12 },
    margin: { l: 8, r: 12, t: 12, b: 8 }, showlegend: false, height: 280,
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--border"), font: { color: css("--text-1") } },
    xaxis: Object.assign({}, axis, extra.xaxis || {}), yaxis: Object.assign({}, axis, extra.yaxis || {}),
  }, Object.fromEntries(Object.entries(extra).filter(([k]) => k !== "xaxis" && k !== "yaxis")));
}
const CFG = { displayModeBar: false, responsive: true };

function renderStatic() {
  const L = D.latest;
  document.getElementById("meta").textContent =
    `Data as of ${L.vintage} · page built ${D.built}`;
  const tiles = document.getElementById("tiles");
  const qs = L.nowcast.map(r => r.quarter);
  L.nowcast.forEach((r, i) => {
    const role = i === qs.length - 1 ? "current quarter" : "previous quarter, not yet published";
    const n = L.news[r.quarter];
    const delta = n ? `${pp(n.post - n.prev)} pp since ${L.previous_vintage}` : "First weekly update";
    tiles.append(el("div", { className: "tile" }, `
      <div class="label">${qLabel(r.quarter)} · ${role}</div>
      <div class="value">${pct(r.nowcast)}</div>
      <div class="bands">68% band ${pct(r.lo68)} to ${pct(r.hi68)} · 90% band ${pct(r.lo90)} to ${pct(r.hi90)}</div>
      <div class="delta">${delta}</div>`));
  });

  const live = document.getElementById("live");
  if (!D.live.length) {
    live.append(el("p", { className: "empty" },
      `No quarter nowcast live has been published yet. The first score arrives when StatCan releases ${qLabel(qs[0])} GDP.`));
  } else {
    const rows = D.live.map(r => `<tr><td>${qLabel(r.quarter)}</td><td>${pct(r.first_release)}</td>
      <td>${pct(r.last_nowcast)}</td><td>${pp(r.last_nowcast - r.first_release)}</td><td>${r.weeks}</td><td>${r.rmse.toFixed(2)}</td></tr>`).join("");
    live.append(el("div", { className: "tablewrap" }, `<table><thead><tr><th>Quarter</th><th>First release</th>
      <th>Last nowcast</th><th>Error, pp</th><th>Weekly nowcasts</th><th>RMSE over all weeks</th></tr></thead><tbody>${rows}</tbody></table>`));
  }

  const B = D.backtest;
  if (B) {
    document.getElementById("bt-sub").textContent =
      `Pseudo-real-time weekly nowcasts for ${qLabel(B.start)} to ${qLabel(B.end)}, excluding 2020 Q1 to 2021 Q1, annualized percentage points.`;
    const imp = b => Math.round(100 * (1 - B.overall.model / B.overall[b]));
    document.getElementById("bt-headline").innerHTML =
      `RMSE <b>${B.overall.model.toFixed(2)}</b> vs ${B.overall.ar1.toFixed(2)} for an AR(1) (${imp("ar1")}% lower) and
       ${B.overall.naive.toFixed(2)} for a naive monthly-GDP tracker (${imp("naive")}% lower), over ${B.overall.n.toLocaleString()} nowcasts.
       The 68% / 90% bands contained the outcome ${Math.round(100 * B.coverage["68"])}% / ${Math.round(100 * B.coverage["90"])}% of the time.`;
    const cap = t => t.charAt(0).toUpperCase() + t.slice(1);
    const rows = B.rmse.map(r => `<tr><td>${cap(r.horizon)}</td><td>${r.model.toFixed(2)}</td><td>${r.ar1.toFixed(2)}</td>
      <td>${r.naive.toFixed(2)}</td><td>${(r.model / r.ar1).toFixed(2)}</td><td>${(r.model / r.naive).toFixed(2)}</td><td>${r.n}</td></tr>`).join("");
    document.getElementById("bt-table").innerHTML = `<table><thead><tr><th>Horizon (when the nowcast was made)</th>
      <th>Model</th><th>AR(1)</th><th>Naive</th><th>Model / AR(1)</th><th>Model / naive</th><th>n</th></tr></thead><tbody>${rows}</tbody></table>`;
  } else {
    document.getElementById("bt").style.display = "none";
  }

  const f = document.getElementById("footer");
  f.innerHTML = (D.repo ? `Code, data and full method: <a href="${D.repo}">${D.repo.replace("https://", "")}</a>. ` : "")
    + "Sources: Statistics Canada, Bank of Canada, FRED. Not an official forecast.";
}

function renderTracks() {
  const box = document.getElementById("tracks");
  box.innerHTML = "";
  const open = D.latest.nowcast.map(r => r.quarter);
  const recent = [...new Set(D.history.map(r => r.quarter))].sort().slice(-4);
  const qs = [...new Set([...recent, ...open])].sort().slice(-2);
  qs.forEach(q => {
    const card = el("div", { className: "card" }, `<h3>${qLabel(q)}</h3>`);
    const div = el("div", { className: "chart" });
    card.append(div); box.append(card);
    const h = D.history.filter(r => r.quarter === q).sort((a, b) => a.vintage < b.vintage ? -1 : 1);
    const x = h.map(r => r.vintage);
    const band = (lo, hi, color) => [
      { x, y: h.map(r => r[hi]), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x, y: h.map(r => r[lo]), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: color, hoverinfo: "skip" }];
    const whisk = (lo, hi, w, color) => ({ x, y: h.map(r => r.nowcast), mode: "markers", hoverinfo: "skip",
      marker: { size: 1, color: "rgba(0,0,0,0)" },
      error_y: { type: "data", symmetric: false, array: h.map(r => r[hi] - r.nowcast),
        arrayminus: h.map(r => r.nowcast - r[lo]), thickness: w, width: 0, color } });
    // a filled band needs at least a few weeks; until then show the bands as whiskers
    const bands = h.length >= 3
      ? [...band("lo90", "hi90", css("--band-90")), ...band("lo68", "hi68", css("--band-68"))]
      : [whisk("lo90", "hi90", 2, css("--band-68")), whisk("lo68", "hi68", 8, css("--band-68"))];
    const traces = [...bands,
      { x, y: h.map(r => r.nowcast), mode: "lines+markers", line: { color: css("--s1"), width: 2 },
        marker: { size: 9, color: css("--s1"), line: { color: css("--surface"), width: 2 } },
        customdata: h.map(r => [r.lo68, r.hi68, r.lo90, r.hi90]),
        hovertemplate: "%{x|%b %d, %Y}<br>Nowcast <b>%{y:.1f}%</b><br>68%: %{customdata[0]:.1f} to %{customdata[1]:.1f}<br>90%: %{customdata[2]:.1f} to %{customdata[3]:.1f}<extra></extra>" }];
    const fr = D.first.find(r => r.quarter === q);
    if (fr) traces.push({ x: [fr.seen_in_vintage], y: [fr.first_release], mode: "markers+text",
      marker: { symbol: "diamond", size: 11, color: css("--ink"), line: { color: css("--surface"), width: 2 } },
      text: [`First release ${pct(fr.first_release)}`], textposition: "top left", textfont: { color: css("--text-1") },
      hovertemplate: "First release %{y:.1f}%<extra></extra>" });
    const xr = x.length > 1 ? undefined : [new Date(new Date(x[0]).getTime() - 35 * 864e5), new Date(new Date(x[0]).getTime() + 35 * 864e5)];
    Plotly.react(div, traces, layout({ xaxis: { type: "date", range: xr, tickformat: "%b %d" },
      yaxis: { ticksuffix: "%", zeroline: true }, hovermode: "closest" }), CFG);
    if (h.length < 3) card.append(el("p", { className: "muted" },
      `${h.length === 1 ? "One point" : "Two points"} so far, one added each week. Thick whisker: 68% band; thin: 90% band.`));
  });
}

function renderNews() {
  const box = document.getElementById("news");
  box.innerHTML = "";
  const L = D.latest;
  if (!Object.keys(L.news).length) {
    box.append(el("p", { className: "empty" }, "The news decomposition needs two weekly snapshots, so it starts with the next update."));
    return;
  }
  Object.entries(L.news).forEach(([q, n]) => {
    const items = n.items.filter(r => Math.abs(r.impact_ann) >= 0.005).slice(0, 10).reverse();
    const card = el("div", { className: "card" },
      `<h3>${qLabel(q)}: ${pct(n.prev, 2)} → ${pct(n.post, 2)}</h3><p class="muted">Since ${L.previous_vintage}</p>`);
    const div = el("div", { className: "chart" });
    card.append(div); box.append(card);
    if (!items.length) { div.replaceWith(el("p", { className: "empty" }, "No release moved this nowcast by 0.01 pp or more.")); return; }
    const lim = Math.max(...items.map(r => Math.abs(r.impact_ann))) * 1.45;
    Plotly.react(div, [{
      type: "bar", orientation: "h", y: items.map(r => r.name), x: items.map(r => r.impact_ann),
      marker: { color: items.map(r => r.impact_ann >= 0 ? css("--pos") : css("--neg")) },
      text: items.map(r => pp(r.impact_ann)), textposition: "outside", cliponaxis: false,
      textfont: { color: css("--text-1"), size: 12 },
      hovertemplate: "%{y}<br><b>%{x:+.2f} pp</b><extra></extra>", width: 0.55 }],
      layout({ height: 70 + 32 * items.length, barcornerradius: 4, hovermode: "closest",
        xaxis: { range: [-lim, lim], zeroline: true, zerolinecolor: css("--text-3"), ticksuffix: "" },
        yaxis: { gridcolor: "rgba(0,0,0,0)", tickfont: { color: css("--text-2"), size: 12 } } }), CFG);
  });
}

function renderBacktest() {
  const B = D.backtest;
  if (!B) return;
  const p = B.path, x = p.map(r => qDate(r.target));
  const lo = -6, hi = 9;
  const off = p.filter(r => r.actual < lo || r.actual > hi).map(r => `${qLabel(r.target)} ${pct(r.actual, 0)}`);
  Plotly.react("bt-path", [
    { x, y: p.map(r => r.actual), mode: "lines", name: "Published GDP", line: { color: css("--ink"), width: 2 },
      customdata: p.map(r => r.target), hovertemplate: "%{customdata}<br>Published <b>%{y:.1f}%</b><extra></extra>" },
    { x, y: p.map(r => r.model), mode: "lines", name: "Model nowcast", line: { color: css("--s1"), width: 2 },
      hovertemplate: "Nowcast <b>%{y:.1f}%</b><extra></extra>" }],
    layout({ hovermode: "x unified", yaxis: { range: [lo, hi], ticksuffix: "%" }, xaxis: { type: "date" },
      shapes: [{ type: "rect", xref: "x", yref: "paper", x0: "2020-01-01", x1: "2021-03-31", y0: 0, y1: 1,
        fillcolor: css("--excluded"), line: { width: 0 }, layer: "below" }],
      margin: { l: 8, r: 12, t: 26, b: 8 },
      annotations: [{ x: "2020-08-15", y: 1, yref: "paper", yanchor: "bottom", showarrow: false,
        text: "2020 Q1–2021 Q1 excluded, off scale", font: { size: 11, color: css("--text-3") } }] }), CFG);
  const xs = B.rmse.map(r => r.horizon.replace("after Q end, month ", "+").replace("month ", "Month ")
    .replace(/^\+(\d)$/, "After Q end<br>+$1 month"));
  const bar = (key, name, color) => ({ type: "bar", name, x: xs, y: B.rmse.map(r => r[key]), marker: { color },
    hovertemplate: `${name}<br>%{x}: <b>%{y:.2f}</b> pp<extra></extra>` });
  Plotly.react("bt-rmse", [bar("model", "Model", css("--s1")), bar("ar1", "AR(1)", css("--s2")), bar("naive", "Naive tracker", css("--s3"))],
    layout({ barmode: "group", bargap: 0.35, bargroupgap: 0.12, barcornerradius: 4, hovermode: "closest",
      yaxis: { rangemode: "tozero" }, xaxis: { tickangle: 0, tickfont: { size: 11, color: css("--text-3") } } }), CFG);
}

function renderCharts() { renderTracks(); renderNews(); renderBacktest(); }
renderStatic();
if (window.Plotly) renderCharts();
else document.querySelectorAll(".chart").forEach(c => c.replaceWith(el("p", { className: "empty" }, "Charts could not load (Plotly CDN unavailable). The tables above carry the numbers.")));
const mq = matchMedia("(prefers-color-scheme: dark)");
mq.addEventListener && mq.addEventListener("change", () => window.Plotly && renderCharts());
new MutationObserver(() => window.Plotly && renderCharts()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
</script>
</body>
</html>
"""
