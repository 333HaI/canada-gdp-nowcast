"""Flash estimates from The Daily, against canned pages (no network)."""
import pandas as pd
import pytest

from nowcast import flash as F


def page(released, sentence, prev="240927a"):
    nav = f'<a class="btn" href="/daily-quotidien/{prev[:6]}/dq{prev}-eng.htm">Previous release</a>' if prev else ""
    return (f"<html><title>The Daily&#160;&#8212;&#160;Gross domestic product by industry, August 2024</title>"
            f"{nav}<p class=\"sd-release-date\">Released:&#160;{released}</p>"
            f"<h2>Advance estimate</h2><p>{sentence} Owing to its preliminary nature, this estimate will be revised.</p>")


@pytest.mark.parametrize("sentence, date, value", [
    ("Advance information indicates that real <a>GDP</a> increased&#160;0.3% in September.", "2024-09-01", 0.3),
    ("Advance information indicates that real GDP edged down 0.1% in July.", "2024-07-01", -0.1),
    ("Advance information indicates that real GDP was essentially unchanged in August.", "2024-08-01", 0.0),
    ("Preliminary information indicates a decrease in real GDP of approximately 0.3% in May.", "2024-05-01", -0.3),
    ("Advanced information indicates an approximate 0.5% increase in real GDP for January 2024.", "2024-01-01", 0.5),
    # the month named first is the one estimated
    ("Preliminary information indicates an approximate 0.4% decrease in real GDP for July giving back half of "
     "June's gains.", "2024-07-01", -0.4),
])
def test_parse_wordings(sentence, date, value):
    p = F.parse(page("2024-10-31", sentence))
    assert p["released"] == "2024-10-31" and p["date"] == date and p["value"] == value
    assert p["previous"] == F.DAILY + "240927/dq240927a-eng.htm"


def test_december_released_in_january_is_previous_year():
    p = F.parse(page("2025-01-31", "Advance information indicates that real GDP increased 0.2% in December."))
    assert p["date"] == "2024-12-01"


def test_release_without_advance_estimate():
    p = F.parse(page("2020-03-31", "Real GDP grew 0.1% in January.", prev=None))
    assert p["date"] is None and p["value"] is None and p["previous"] is None


class Resp:
    def __init__(self, text="", payload=None, status=200):
        self.text, self.payload, self.status_code = text, payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.payload


class FakeDaily:
    def __init__(self, pages, release_time):
        self.pages, self.release_time, self.gets = pages, release_time, []

    def post(self, url, json=None, timeout=None):
        return Resp(payload=[{"object": {"releaseTime": self.release_time}}])

    def get(self, url, timeout=None):
        self.gets.append(url)
        key = url.rsplit("dq", 1)[1].split("-")[0]
        return Resp(self.pages[key]) if key in self.pages else Resp(status=404)


def test_update_walks_back_to_last_known_release(tmp_path):
    csv = tmp_path / "gdp_flash.csv"
    csv.write_text("date,value,release_date\n2024-08-01,0.0,2024-09-27\n", encoding="utf-8")
    pages = {
        "241223a": page("2024-12-23", "Advance information indicates that real GDP decreased 0.1% in November.",
                        prev="241129a"),
        "241129a": page("2024-11-29", "Advance information indicates that real GDP increased 0.1% in October.",
                        prev="241031a"),
        "241031a": page("2024-10-31", "Advance information indicates that real GDP increased 0.3% in September.",
                        prev="240927a"),
        "240927a": page("2024-09-27", "Advance information indicates that real GDP was essentially unchanged "
                        "in August.", prev="240830a"),
    }
    http = FakeDaily(pages, "2024-12-23T08:30")
    new = F.update(csv, http=http, pause=0)
    assert list(new["date"]) == ["2024-09-01", "2024-10-01", "2024-11-01"]
    assert not any("240830" in u for u in http.gets)  # stopped at the known release
    out = pd.read_csv(csv)
    assert list(out["date"]) == ["2024-08-01", "2024-09-01", "2024-10-01", "2024-11-01"]
    assert list(out["value"]) == [0.0, 0.3, 0.1, -0.1]
    assert F.update(csv, http=FakeDaily(pages, "2024-12-23T08:30"), pause=0).empty
