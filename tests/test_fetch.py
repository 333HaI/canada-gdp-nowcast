"""Fetch clients against canned responses (no network)."""
import pandas as pd

from nowcast.config import Series
from nowcast.fetch import fetch_boc, fetch_statcan, load_snapshot, save_snapshot
from nowcast.config import load_config


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def mk(key, source, ids, native_freq=None, freq="M"):
    return Series(key=key, name=key, source=source, ids=tuple(ids), freq=freq,
                  transform="dlog", blocks=("global",), release_lag=0, native_freq=native_freq)


def test_statcan_parses_and_maps_spliced_ids_to_one_key():
    payload = [
        {"status": "SUCCESS", "object": {"vectorId": 1, "vectorDataPoint": [
            {"refPer": "2017-12-01", "value": 10.0, "releaseTime": "2018-02-01T08:30"}]}},
        {"status": "SUCCESS", "object": {"vectorId": 2, "vectorDataPoint": [
            {"refPer": "2018-01-01", "value": 20.0, "releaseTime": "2018-03-01T08:30"}]}},
    ]
    http = FakeSession(payload)
    df = fetch_statcan([mk("permits", "statcan", ["1", "2"])], "2017-01-01", http)
    assert http.calls[0][1]["vectorIds"] == "1,2"
    assert list(df["key"]) == ["permits", "permits"]
    assert list(df["source_id"]) == ["1", "2"]


def test_statcan_raises_on_missing_vector():
    http = FakeSession([{"status": "FAILED", "object": "bad vector"}])
    try:
        fetch_statcan([mk("x", "statcan", ["99"])], "2017-01-01", http)
    except RuntimeError as e:
        assert "99" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_boc_daily_averaged_to_months():
    payload = {"observations": [
        {"d": "2024-01-02", "R": {"v": "5.00"}, "M.X": {"v": "100"}},
        {"d": "2024-01-03", "R": {"v": "4.00"}},
        {"d": "2024-02-01", "R": {"v": "3.00"}, "M.X": {"v": "110"}},
    ]}
    df = fetch_boc([mk("rate", "boc", ["R"], native_freq="D"), mk("idx", "boc", ["M.X"])],
                   "2024-01-01", FakeSession(payload))
    rate = df[df["key"] == "rate"].set_index("date")["value"]
    assert rate.loc["2024-01-01"] == 4.5 and rate.loc["2024-02-01"] == 3.0
    idx = df[df["key"] == "idx"].set_index("date")["value"]
    assert list(idx) == [100.0, 110.0]


def test_snapshot_round_trip(tmp_path):
    cfg = load_config()
    raw = pd.DataFrame({"key": ["gdp_q"], "source_id": ["62305752"],
                        "date": pd.to_datetime(["2026-04-01"]), "value": [1.0],
                        "release_time": [None]})
    save_snapshot(raw, {"statcan": "ok"}, cfg, vintage="2026-01-02", root=tmp_path)
    back = load_snapshot("latest", root=tmp_path)
    assert back.attrs["vintage"] == "2026-01-02"
    assert back.loc[0, "source_id"] == "62305752" and back.loc[0, "value"] == 1.0
