"""Append-only live record, first-release capture, and the page build."""
import json

import pandas as pd
import pytest

from nowcast import history as H
from nowcast import report as R


def nc(values):
    return pd.DataFrame({
        "quarter": list(values), "nowcast": list(values.values()),
        "lo68": 0.0, "hi68": 3.0, "lo90": -1.0, "hi90": 4.0, "qoq": 0.5, "sd_qoq": 0.25,
    }).set_index("quarter")


def test_history_is_append_only(tmp_path):
    assert H.record_nowcast("2026-10-23", nc({"2026Q3": 2.0, "2026Q4": 1.5}), "g", tmp_path) == 2
    # same week again with different numbers: nothing is rewritten
    assert H.record_nowcast("2026-10-23", nc({"2026Q3": 9.9}), "g", tmp_path) == 0
    assert H.record_nowcast("2026-10-30", nc({"2026Q3": 2.2}), "g", tmp_path) == 1
    h = H.read(H.HISTORY, tmp_path)
    assert list(h["vintage"]) == ["2026-10-23", "2026-10-23", "2026-10-30"]
    assert h.loc[0, "nowcast"] == 2.0


def test_first_release_only_for_nowcast_quarters(tmp_path):
    H.record_nowcast("2026-10-23", nc({"2026Q3": 2.0}), "g", tmp_path)
    target = pd.Series([0.4, 0.5], index=pd.PeriodIndex(["2026Q2", "2026Q3"], freq="Q"))
    # 2026Q2 was published before launch: its value here is revised, so it is skipped
    assert H.record_first_releases("2026-11-28", target, tmp_path) == 1
    f = H.read(H.FIRST, tmp_path)
    assert list(f["quarter"]) == ["2026Q3"] and f.loc[0, "seen_in_vintage"] == "2026-11-28"
    # a later revision never replaces the first release
    revised = pd.Series([0.9], index=pd.PeriodIndex(["2026Q3"], freq="Q"))
    assert H.record_first_releases("2027-02-27", revised, tmp_path) == 0
    assert H.read(H.FIRST, tmp_path).loc[0, "first_release_qoq"] == pytest.approx(0.5)


def test_scorecard_and_live_rmse(tmp_path):
    H.record_nowcast("2026-10-23", nc({"2026Q3": 2.0}), "g", tmp_path)
    H.record_nowcast("2026-10-30", nc({"2026Q3": 3.0}), "g", tmp_path)
    assert H.live_rmse(tmp_path).empty
    H.record_first_releases("2026-11-28", pd.Series([0.5], index=pd.PeriodIndex(["2026Q3"], freq="Q")), tmp_path)
    live = H.live_rmse(tmp_path)
    fr = live.loc[0, "first_release"]
    assert live.loc[0, "last_nowcast"] == 3.0 and live.loc[0, "weeks"] == 2
    assert live.loc[0, "rmse"] == pytest.approx((((2 - fr) ** 2 + (3 - fr) ** 2) / 2) ** 0.5, abs=1e-3)


def test_report_builds_self_contained_page(tmp_path, monkeypatch):
    out, site = tmp_path / "out", tmp_path / "site"
    H.record_nowcast("2026-10-23", nc({"2026Q3": 2.0}), "g", out)
    latest = {"vintage": "2026-10-23", "previous_vintage": None, "news": {},
              "nowcast": nc({"2026Q3": 2.0}).reset_index().to_dict("records")}
    (out / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    monkeypatch.setattr(R, "backtest_data", lambda out=None: None)
    path = R.build(out, site, readme=False)
    html = path.read_text(encoding="utf-8")
    assert "<title>Canada GDP Nowcast</title>" in html and "__DATA__" not in html
    data = json.loads(html.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    assert data["latest"]["vintage"] == "2026-10-23" and len(data["history"]) == 1
    assert (site / ".nojekyll").exists()


def test_readme_block_is_rewritten_between_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# T\n<!-- nowcast:start (auto) -->\nold\n<!-- nowcast:end -->\nrest\n", encoding="utf-8")
    data = {"latest": {"vintage": "2026-10-30",
                       "nowcast": [{"quarter": "2026Q3", "nowcast": 2.04, "lo68": -0.5, "hi68": 3.0}]},
            "backtest": None}
    assert R.update_readme(data, readme)
    text = readme.read_text(encoding="utf-8")
    assert "old" not in text and text.endswith("<!-- nowcast:end -->\nrest\n")
    assert "2026Q3 2.0% (68%: -0.5 to 3.0)" in text
    assert not R.update_readme(data, readme)  # idempotent
