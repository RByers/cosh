import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cosh import radar

D = dt.date
BROWSERS = {
    "Chrome": {"is_chromium": True, "kind": "browser"},
    "Edge": {"is_chromium": True, "kind": "browser"},
    "Samsung Internet": {"is_chromium": True, "kind": "browser"},
    "Chrome Mobile WebView": {"is_chromium": True, "kind": "webview"},
    "Safari": {"is_chromium": False, "kind": "browser"},
    "Other": {"is_chromium": False, "kind": "other"},
}


def response(start, rows):
    """Fake Radar timeseries_groups response: rows = list of {browser: percent}."""
    names = set().union(*rows)
    serie = {"timestamps": [f"{start + dt.timedelta(days=i)}T00:00:00Z" for i in range(len(rows))]}
    for n in names:
        serie[n] = [str(r[n]) if n in r else None for r in rows]
    return {"success": True, "result": {"meta": {"aggInterval": "ONE_DAY"}, "serie_0": serie}}


class NormalizeTest(unittest.TestCase):
    def test_renormalize_among_chromium_browsers(self):
        n = radar.renormalize({"Chrome": 0.6, "Edge": 0.15, "Samsung Internet": 0.05,
                               "Chrome Mobile WebView": 0.2, "Safari": 0.3, "Other": 0.1,
                               "Mystery": 0.05}, BROWSERS)
        self.assertAlmostEqual(n["Chrome"][0], 0.75)
        self.assertAlmostEqual(n["Edge"][0], 0.1875)
        self.assertAlmostEqual(sum(v[0] for v in n.values() if v[0] is not None), 1.0)
        self.assertIsNone(n["Chrome Mobile WebView"][0])          # webview excluded ...
        self.assertAlmostEqual(n["Chrome Mobile WebView"][1], 0.2)  # ... but in the _all variant
        self.assertAlmostEqual(n["Chrome"][1], 0.6)
        for b in ("Safari", "Other", "Mystery"):                  # non-Chromium / unknown
            self.assertEqual(n[b], (None, None))

    def test_renormalize_no_chromium(self):
        self.assertEqual(radar.renormalize({"Safari": 1.0}, BROWSERS), {"Safari": (None, None)})

    def test_periods(self):
        self.assertEqual(radar.period_of(D(2026, 11, 1), "week"), ("2026-W44", D(2026, 10, 26), D(2026, 11, 1)))
        self.assertEqual(radar.period_of(D(2021, 1, 3), "week")[0], "2020-W53")
        self.assertEqual(radar.period_of(D(2024, 2, 10), "month"), ("2024-02", D(2024, 2, 1), D(2024, 2, 29)))

    def test_aggregate_mean_with_missing_as_zero(self):
        daily = {D(2026, 10, 26): {"Chrome": 0.5, "Edge": 0.1}, D(2026, 10, 27): {"Chrome": 0.7}}
        (key, (days, shares)), = radar.aggregate(daily, "week").items()
        self.assertEqual((key[0], days), ("2026-W44", 2))
        self.assertAlmostEqual(shares["Chrome"], 0.6)
        self.assertAlmostEqual(shares["Edge"], 0.05)

    def test_parse_serie_percent_and_window(self):
        resp = response(D(2026, 3, 30), [{"Chrome": "50", "other": "50"}] * 3)
        out = radar.parse_serie(resp, D(2026, 3, 30), D(2026, 4, 1))   # 3rd point is past dateEnd
        self.assertEqual(sorted(out), [D(2026, 3, 30), D(2026, 3, 31)])
        self.assertEqual(out[D(2026, 3, 30)], {"Chrome": 0.5, "Other": 0.5})

    def test_quarter_chunks(self):
        self.assertEqual(list(radar.quarter_chunks(D(2020, 9, 1), D(2021, 2, 10))),
                         [(D(2020, 9, 1), D(2020, 10, 1)), (D(2020, 10, 1), D(2021, 1, 1)),
                          (D(2021, 1, 1), D(2021, 2, 10))])


class FetchTest(unittest.TestCase):
    def test_fetch_is_incremental_and_writes_table(self):
        calls = []

        def fake_get(self, path, params):
            calls.append(params)
            s = D.fromisoformat(params["dateStart"][:10])
            e = D.fromisoformat(params["dateEnd"][:10])
            rows = [{"Chrome": 60, "Edge": 15, "Safari": 25}] * ((e - s).days + 1)
            return 200, response(s, rows), "", "url"

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(radar, "RAW_DIR", Path(tmp) / "raw"), \
                mock.patch.object(radar.RadarClient, "get", fake_get):
            log = io.StringIO()
            kw = dict(start=D(2026, 9, 28), devices=("ALL",), token="t", log=log)
            radar.fetch(today=D(2026, 10, 5), **kw)
            self.assertEqual(len(calls), 2)                 # Q3 tail (complete) + Q4 so far
            radar.fetch(today=D(2026, 10, 5), **kw)
            self.assertEqual(len(calls), 2)                 # nothing new
            radar.fetch(today=D(2026, 10, 6), **kw)
            self.assertEqual(len(calls), 3)                 # only the open quarter again
            out = Path(tmp) / "share.csv"
            with mock.patch.object(radar, "load_browsers", return_value=BROWSERS):
                rows = radar.write_table(out=out, log=log)
            wk = [r for r in rows if r["period"] == "2026-W40" and r["browser"] == "Chrome"]
            self.assertEqual(wk[0]["chromium_share"], "0.800000")
            self.assertEqual(wk[0]["days"], 7)
            self.assertTrue(out.read_text().startswith("period,period_start"))


if __name__ == "__main__":
    unittest.main()
