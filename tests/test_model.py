"""Model wrapper and backtest helpers on small synthetic data (no network)."""
import numpy as np
import pandas as pd
import pytest

from nowcast import backtest as B
from nowcast import model as M
from nowcast.config import Config, Series


def mk(key, freq="M", lag=0, blocks=("global",)):
    return Series(key=key, name=key, source="statcan", ids=("1",), freq=freq,
                  transform="dlog", blocks=blocks, release_lag=lag)


def test_release_dates_and_as_of():
    cfg = Config(series=(mk("a", lag=10),), start="2000-01-01", target="a")
    idx = pd.period_range("2024-01", periods=3, freq="M")
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=idx)
    rel = B.release_dates(df, cfg)
    assert rel.loc[pd.Period("2024-01", "M"), "a"] == pd.Timestamp("2024-02-10")
    seen = B.as_of(df, rel, pd.Timestamp("2024-03-10"))
    assert list(seen["a"].notna()) == [True, True, False]


def test_ar1_recovers_parameters_and_iterates():
    rng = np.random.default_rng(0)
    y = [0.5]
    for _ in range(400):
        y.append(0.2 + 0.6 * y[-1] + rng.normal(0, 0.01))
    s = pd.Series(y, index=pd.period_range("1900Q1", periods=len(y), freq="Q"))
    last = s.index[-1]
    f2 = B.ar1_forecast(s, last + 2)
    expect = 0.2 + 0.6 * (0.2 + 0.6 * s.iloc[-1])
    assert f2 == pytest.approx(expect, abs=0.01)


def test_naive_tracker_exact_when_quarter_complete_and_trend_filled():
    idx = pd.period_range("2023-01", "2024-06", freq="M")
    lv = pd.Series(100 * 1.01 ** np.arange(len(idx)), index=idx)
    # complete data: growth of quarterly averages = 3 months of 1% growth
    assert B.naive_forecast(lv, pd.Period("2024Q2", "Q")) == pytest.approx(300 * np.log(1.01))
    # last 4 months missing: filled at the trailing average growth (1%), same answer
    partial = lv.copy()
    partial.iloc[-4:] = np.nan
    assert B.naive_forecast(partial, pd.Period("2024Q2", "Q")) == pytest.approx(300 * np.log(1.01))


@pytest.fixture(scope="module")
def toy():
    """Two monthly indicators driven by one AR(1) factor, plus quarterly GDP."""
    rng = np.random.default_rng(1)
    n = 240
    f = np.zeros(n)
    for t in range(1, n):
        f[t] = 0.7 * f[t - 1] + rng.normal()
    idx = pd.period_range("2000-01", periods=n, freq="M")
    monthly = pd.DataFrame({"x1": f + rng.normal(0, 0.3, n), "x2": 0.5 * f + rng.normal(0, 0.3, n)},
                           index=idx)
    g = pd.Series(f, index=idx).rolling(3).mean().resample("Q").last()
    quarterly = pd.DataFrame({"gdp": g + rng.normal(0, 0.1, len(g))})
    quarterly.iloc[-2:] = np.nan  # last two quarters unpublished
    cfg = Config(series=(mk("x1"), mk("x2"), mk("gdp", freq="Q")), start="2000-01-01", target="gdp")
    mm, qq = M.prepare(monthly, quarterly, cfg, idx[-1])
    res = M.fit(mm, qq, cfg, M.Spec(blocks=("global",), maxiter=50))
    return cfg, mm, qq, res


def test_nowcast_bands_are_ordered(toy):
    cfg, mm, qq, res = toy
    qs = M.open_quarters(qq, "gdp", mm.index[-1].to_timestamp())
    assert [str(q) for q in qs] == [str(qq.index[-2]), str(qq.index[-1])]
    nc = M.nowcast(res, qs, "gdp")
    for _, r in nc.iterrows():
        assert r.lo90 < r.lo68 < r.nowcast < r.hi68 < r.hi90


def test_news_impacts_sum_to_revision_of_nowcast(toy):
    cfg, mm, qq, res = toy
    old = mm.copy()
    old.iloc[-2:] = np.nan  # previous vintage: last two months not yet out
    res_old = M.refilter(res, old, qq)
    q = qq.index[-1]
    n = M.news(res, res_old, q, "gdp")
    assert set(n["series"]) == {"x1", "x2"}
    assert n["impact_qoq"].sum() == pytest.approx(n.attrs["post_qoq"] - n.attrs["prev_qoq"], abs=1e-8)
    assert n["impact_ann"].sum() == pytest.approx(n.attrs["post"] - n.attrs["prev"], abs=1e-8)


def test_prepare_drops_constant_and_short_series():
    idx = pd.period_range("2000-01", periods=40, freq="M")
    m = pd.DataFrame({"ok": np.arange(40.0), "flat": 0.0, "short": np.nan}, index=idx)
    m.iloc[:5, 2] = [1, 2, 3, 4, 5]
    q = pd.DataFrame({"gdp": np.arange(14.0)}, index=pd.period_range("2000Q1", periods=14, freq="Q"))
    cfg = Config(series=(mk("ok"), mk("flat"), mk("short"), mk("gdp", freq="Q")),
                 start="2000-01-01", target="gdp")
    mm, _ = M.prepare(m, q, cfg, idx[-1])
    assert list(mm) == ["ok"]


def test_prepare_drops_series_kept_out_of_the_model():
    idx = pd.period_range("2000-01", periods=40, freq="M")
    m = pd.DataFrame({"x": np.arange(40.0), "kept_out": np.arange(40.0) ** 0.5}, index=idx)
    q = pd.DataFrame({"gdp": np.arange(14.0)}, index=pd.period_range("2000Q1", periods=14, freq="Q"))
    off = Series(key="kept_out", name="kept_out", source="manual", ids=("f.csv",), freq="M",
                 transform="level", blocks=("global",), release_lag=0, model=False)
    cfg = Config(series=(mk("x"), off, mk("gdp", freq="Q")), start="2000-01-01", target="gdp")
    mm, _ = M.prepare(m, q, cfg, idx[-1])
    assert list(mm) == ["x"]
