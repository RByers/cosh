import datetime as dt
import io
import json
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
    "Instagram": {"is_chromium": True, "kind": "in_app"},
    "ChromeHeadless": {"is_chromium": True, "kind": "bot"},
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
    def test_renormalize_includes_webview_and_in_app(self):
        n = radar.renormalize({"Chrome": 0.5, "Edge": 0.15, "Samsung Internet": 0.05,
                               "Chrome Mobile WebView": 0.2, "Instagram": 0.1, "ChromeHeadless": 0.01,
                               "Safari": 0.3, "Other": 0.1, "Mystery": 0.05}, BROWSERS)
        self.assertAlmostEqual(n["Chrome"], 0.5)
        self.assertAlmostEqual(n["Chrome Mobile WebView"], 0.2)
        self.assertAlmostEqual(n["Instagram"], 0.1)
        self.assertAlmostEqual(sum(v for v in n.values() if v is not None), 1.0)
        for b in ("ChromeHeadless", "Safari", "Other", "Mystery"):  # bot / non-Chromium / unknown
            self.assertIsNone(n[b])

    def test_renormalize_no_chromium(self):
        self.assertEqual(radar.renormalize({"Safari": 1.0}, BROWSERS), {"Safari": None})

    def test_exclude_ios(self):
        # 20% of requests are iOS; on iOS, Chrome (CriOS) is 10% and Safari 90%.
        out = radar.exclude_ios({"Chrome": 0.42, "Safari": 0.18, "Edge": 0.4},
                                {"Chrome": 0.1, "Safari": 0.9}, {"IOS": 0.2, "ANDROID": 0.8})
        self.assertAlmostEqual(out["Chrome"], 0.5)
        self.assertAlmostEqual(out["Safari"], 0.0)
        self.assertAlmostEqual(out["Edge"], 0.5)
        # a browser in the iOS top N but over-subtracted (rounding) clamps at 0
        self.assertEqual(radar.exclude_ios({"A": 0.01}, {"A": 0.2}, {"IOS": 0.5})["A"], 0.0)

    def test_request_params_per_series(self):
        p = radar.request_params("ALL", "1d", D(2026, 1, 1), D(2026, 2, 1), 50, "browser_ios")
        self.assertEqual((p["os"], p["limitPerGroup"]), ("IOS", 50))
        p = radar.request_params("ALL", "1d", D(2026, 1, 1), D(2026, 2, 1), 50, "os")
        self.assertNotIn("limitPerGroup", p)
        self.assertNotIn("os", p)
        self.assertEqual(radar.series_of(dict(p, endpoint=radar.OS_ENDPOINT)), "os")

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
            if path == radar.OS_ENDPOINT:
                row = {"IOS": 20, "ANDROID": 80}
            elif params.get("os") == "IOS":
                row = {"Chrome": 25, "Safari": 75}            # Chrome iOS is WebKit
            else:
                row = {"Chrome": 50, "Edge": 15, "Chrome Mobile WebView": 15, "Safari": 20}
            return 200, response(s, [row] * ((e - s).days + 1)), "", "url"

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(radar, "RAW_DIR", Path(tmp) / "raw"), \
                mock.patch.object(radar.RadarClient, "get", fake_get):
            log = io.StringIO()
            kw = dict(start=D(2026, 9, 28), devices=("ALL",), token="t", log=log)
            radar.fetch(today=D(2026, 10, 5), **kw)
            self.assertEqual(len(calls), 6)                 # 3 series x (Q3 tail + Q4 so far)
            radar.fetch(today=D(2026, 10, 5), **kw)
            self.assertEqual(len(calls), 6)                 # nothing new
            radar.fetch(today=D(2026, 10, 6), **kw)
            self.assertEqual(len(calls), 9)                 # only the open quarter again
            out = Path(tmp) / "share.csv"
            with mock.patch.object(radar, "load_browsers", return_value=BROWSERS):
                rows = radar.write_table(out=out, log=log)
            wk = {r["browser"]: r for r in rows if r["period"] == "2026-W40" and r["granularity"] == "week"}
            # non-iOS: Chrome (50-0.2*25)/0.8 = 56.25%, Edge 18.75%, WebView 18.75%, Safari 6.25%
            self.assertEqual(wk["Chrome"]["raw_share"], "0.562500")
            self.assertEqual(wk["Chrome"]["chromium_share"], "0.600000")       # 56.25 / 93.75
            self.assertEqual(wk["Chrome Mobile WebView"]["chromium_share"], "0.200000")
            self.assertEqual(wk["Chrome"]["days"], 7)
            self.assertTrue(out.read_text().startswith("period,period_start"))

    def test_days_without_ios_series_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(radar, "RAW_DIR", Path(tmp)):
            for series, row in (("browser", {"Chrome": 100}), ("os", {"IOS": 10, "ANDROID": 90})):
                params = radar.request_params("ALL", "1d", D(2026, 1, 1), D(2026, 1, 3), 50, series)
                params["endpoint"] = radar.SERIES[series][0]
                rec = {"request": params, "status": 200,
                       "response": response(D(2026, 1, 1), [row, row])}
                radar.cache_path("ALL", "1d", D(2026, 1, 1), D(2026, 1, 3), series).write_text(
                    json.dumps(rec))
            self.assertEqual(dict(radar.load_cached()), {})   # no iOS series: can't remove iOS


if __name__ == "__main__":
    unittest.main()
