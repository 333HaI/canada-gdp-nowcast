import numpy as np
import pandas as pd
import pytest

from nowcast.config import load_config
from nowcast.transform import annualize, apply_mask, build_panel, splice, transform_series


def months(start, n):
    return pd.period_range(start, periods=n, freq="M")


def test_splice_with_overlap_keeps_growth_of_both_pieces():
    old = pd.Series([100.0, 110.0, 121.0, 133.1], index=months("2020-01", 4))
    new = pd.Series([50.0, 55.0, 60.5], index=months("2020-03", 3))
    out = splice({"a": old, "b": new}, ("a", "b"))
    assert list(out.index) == list(months("2020-01", 5))
    # newer series wins on the overlap, older one is rescaled to it
    assert out.loc[pd.Period("2020-03", "M")] == 50.0
    growth = np.log(out).diff().dropna()
    assert np.allclose(growth, np.log(1.1))
    assert out.attrs["seams"] == []


def test_splice_without_overlap_records_seam():
    old = pd.Series([1.0, 2.0], index=months("2017-11", 2))
    new = pd.Series([500.0, 510.0], index=months("2018-01", 2))
    out = splice({"a": old, "b": new}, ("a", "b"))
    assert out.attrs["seams"] == [pd.Period("2018-01", "M")]
    y = transform_series(out, "dlog", out.attrs["seams"])
    assert np.isnan(y.loc[pd.Period("2018-01", "M")])
    assert y.loc[pd.Period("2018-02", "M")] == pytest.approx(100 * np.log(510 / 500))


def test_transforms():
    x = pd.Series([100.0, 105.0, 0.0, 110.0], index=months("2021-01", 4))
    d = transform_series(x, "dlog")
    assert d.iloc[1] == pytest.approx(100 * np.log(1.05))
    assert np.isnan(d.iloc[2]) and np.isnan(d.iloc[3])  # non-positive level -> missing
    assert list(transform_series(x, "diff").iloc[1:]) == [5.0, -105.0, 110.0]
    with pytest.raises(ValueError):
        transform_series(x, "bogus")


def test_mask_monthly_and_quarterly():
    m = pd.DataFrame({"x": 1.0}, index=months("2020-01", 12))
    mm = apply_mask(m, [("2020-03", "2020-12")])
    assert mm["x"].notna().sum() == 2
    q = pd.DataFrame({"x": 1.0}, index=pd.period_range("2019Q4", "2021Q1", freq="Q"))
    qm = apply_mask(q, [("2020-03", "2020-12")])
    # any quarter containing a masked month is masked
    assert list(qm["x"].isna()) == [False, True, True, True, True, False]


def test_annualize():
    assert annualize(1.0) == pytest.approx(100 * (np.exp(0.04) - 1))


def test_config_loads_and_is_consistent():
    cfg = load_config()
    assert cfg.get(cfg.target).freq == "Q"
    assert 20 <= len(cfg.monthly) <= 30
    statcan_ids = [i for s in cfg.by_source("statcan") for i in s.ids]
    assert len(statcan_ids) == len(set(statcan_ids))


def test_build_panel_shapes():
    cfg = load_config()
    rows = []
    for k, sid, freq in [("gdp_m", "65201210", "MS"), ("lfs_emp", "2062811", "MS"),
                         ("gdp_q", "62305752", "QS")]:
        idx = pd.date_range("2019-01-01", periods=8, freq=freq)
        rows += [{"key": k, "source_id": sid, "date": d, "value": 100 * 1.01 ** i,
                  "release_time": None} for i, d in enumerate(idx)]
    raw = pd.DataFrame(rows)
    monthly, quarterly = build_panel(raw, cfg, mask=False)
    assert monthly.index.freqstr.startswith("M") and quarterly.index.freqstr.startswith("Q")
    assert set(monthly) == {"gdp_m", "lfs_emp"} and set(quarterly) == {"gdp_q"}
    assert np.allclose(monthly["gdp_m"].dropna(), 100 * np.log(1.01))
