import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from fetch import refresh, validate
from ledger import update_ledger
from quant import evaluate, opening_ema, research
from sources import SOURCES, health

NOW = dt.datetime(2026, 11, 25, 23, tzinfo=dt.timezone.utc)


def prices():
    dates = pd.bdate_range(end="2026-11-24", periods=100)
    values = np.linspace(70, 80, 100)
    values[-1] = 60
    return pd.Series(values, index=dates)


def good_sources(now=NOW):
    return {key: {"status": "ok", "last_success": now.isoformat(), "last_attempt": now.isoformat()} for key in SOURCES}


def temporary():
    return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)


class SignalTests(unittest.TestCase):
    def test_latest_signal_and_no_future_leakage(self):
        series = prices()
        expected = evaluate(series, NOW)
        self.assertEqual(expected["signal"], 1)
        changed = pd.concat([series, pd.Series([10000], index=pd.to_datetime(["2026-11-27"]))])
        self.assertEqual(expected, evaluate(changed, NOW))

    def test_insufficient_and_flat_series(self):
        for series in (pd.Series(dtype=float), prices().iloc[:10], prices() * 0 + 4):
            result = evaluate(series, NOW)
            self.assertIsNone(result["signal"])
            self.assertEqual(result["state"], "insufficient")
            json.dumps(result, allow_nan=False)

    def test_stale_signal_is_paused(self):
        result = evaluate(prices(), NOW + dt.timedelta(days=20))
        self.assertEqual(result["state"], "stale")
        self.assertIsNone(result["signal"])

    def test_duplicate_dates_and_non_finite_values_are_cleaned(self):
        series = prices()
        corrupted = pd.concat([series, series.iloc[-1:]])
        self.assertEqual(evaluate(series, NOW), evaluate(corrupted, NOW))
        corrupted.iloc[-1] = np.inf
        json.dumps(evaluate(corrupted, NOW), allow_nan=False)

    def test_historical_diagnostic_uses_two_observation_lag(self):
        series = prices()
        result = evaluate(series, NOW)
        z = (series - series.rolling(20).mean()) / series.rolling(20).std()
        direction = pd.Series(np.where(z < -1, 1, np.where(z > 1, -1, 0)), index=series.index).shift(2)
        valid = z.shift(2).notna() & direction.ne(0) & series.diff().notna()
        scores = (direction * series.diff())[valid]
        self.assertEqual(result["observations"], len(scores))
        if len(scores):
            self.assertAlmostEqual(result["directional_accuracy"], float((scores > 0).mean()))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        self.metrics = {key: prices() for key in ("wti", "brent", "wti_brent", "crack_321")}
        self.signals = research(self.metrics, NOW)

    def test_preview_and_failed_fetch_never_issue(self):
        self.assertEqual(update_ledger(self.signals, self.metrics, self.path, good_sources(), now=NOW)["issued"], 0)
        self.assertFalse(self.path.exists())
        self.assertEqual(update_ledger(self.signals, self.metrics, self.path, {}, record=True, now=NOW)["issued"], 0)

    def test_composite_requires_every_source(self):
        status = good_sources()
        status["gasoline_nyh"]["status"] = "error"
        result = update_ledger(self.signals, self.metrics, self.path, status, True, NOW)
        self.assertEqual({entry["metric"] for entry in result["entries"]}, {"wti", "brent", "wti_brent"})

    def test_records_once_without_backdating_or_overwriting(self):
        result = update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)
        self.assertEqual(result["issued"], 4)
        entry = result["entries"][0]
        self.assertEqual(entry["due_on"], "2026-12-02")
        self.assertEqual(entry["issued_at"], NOW.isoformat())
        self.assertEqual(entry["as_of"], "2026-11-24")
        before = self.path.read_bytes()
        self.signals["signals"]["wti"]["value"] = 999
        self.assertEqual(update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)["issued"], 4)
        self.assertEqual(before, self.path.read_bytes())

    def test_outcome_resolves_once_and_freezes(self):
        update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)
        later = NOW + dt.timedelta(days=9)
        for series in self.metrics.values():
            series.loc[pd.Timestamp("2026-12-01")] = 999
            series.loc[pd.Timestamp("2026-12-02")] = 65
        result = update_ledger(self.signals, self.metrics, self.path, good_sources(later), True, later)
        self.assertEqual(result["resolved"], 4)
        self.assertEqual(result["hits"], 4)
        before = self.path.read_bytes()
        for series in self.metrics.values():
            series.loc[pd.Timestamp("2026-12-02")] = -999
        update_ledger(self.signals, self.metrics, self.path, good_sources(later), True, later)
        self.assertEqual(before, self.path.read_bytes())

    def test_long_missing_interval_is_unscored(self):
        update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)
        later = NOW + dt.timedelta(days=25)
        for series in self.metrics.values():
            series.loc[pd.Timestamp("2026-12-15")] = 65
        result = update_ledger(self.signals, self.metrics, self.path, good_sources(later), True, later)
        self.assertEqual(result["unscored"], 4)
        self.assertIsNone(result["hit_rate"])

    def test_no_future_outcomes_and_failed_refresh_cannot_resolve(self):
        update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)
        for series in self.metrics.values():
            series.loc[pd.Timestamp("2026-12-02")] = 65
        self.assertEqual(update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)["resolved"], 0)
        later = NOW + dt.timedelta(days=10)
        self.assertEqual(update_ledger(self.signals, self.metrics, self.path, {}, True, later)["resolved"], 0)

    def test_flat_move_counts_as_miss(self):
        update_ledger(self.signals, self.metrics, self.path, good_sources(), True, NOW)
        later = NOW + dt.timedelta(days=9)
        for series in self.metrics.values():
            series.loc[pd.Timestamp("2026-12-02")] = 60
        result = update_ledger(self.signals, self.metrics, self.path, good_sources(later), True, later)
        self.assertEqual(result["resolved"], 4)
        self.assertEqual(result["hits"], 0)


class SourceTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"date": prices().index, "value": prices().values})

    def test_rejects_non_finite_duplicate_and_future_rows(self):
        for mode in ("nonfinite", "duplicate", "future"):
            frame = self.frame()
            if mode == "nonfinite":
                frame.loc[0, "value"] = np.nan
            elif mode == "duplicate":
                frame.loc[1, "date"] = frame.loc[0, "date"]
            else:
                frame.loc[99, "date"] = pd.Timestamp("2026-12-01")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate("wti", frame, now=NOW)

    def test_rejects_history_regression_but_allows_negative_oil(self):
        old = self.frame()
        with self.assertRaises(ValueError):
            validate("wti", old.iloc[:-1], old, NOW)
        with self.assertRaises(ValueError):
            validate("wti", old.iloc[40:], old, NOW)
        old.loc[0, "value"] = -37.63
        self.assertEqual(validate("wti", old, now=NOW).value.iloc[0], -37.63)
        with self.assertRaises(ValueError):
            validate("crude_stocks", old, now=NOW)

    def test_failed_source_keeps_cache_and_records_failure(self):
        with temporary() as folder:
            data = Path(folder)
            self.frame().to_csv(data / "wti.csv", index=False)
            before = (data / "wti.csv").read_bytes()
            with patch("fetch.fetch_eia", side_effect=OSError("test outage")), patch("fetch.fetch_cftc", side_effect=OSError("test outage")):
                self.assertEqual(refresh(data, NOW), 1)
            self.assertEqual(before, (data / "wti.csv").read_bytes())
            state = json.loads((data / "source_status.json").read_text())
            self.assertEqual(state["wti"]["status"], "error")
            self.assertNotIn("last_success", state["wti"])

    def test_partial_success_updates_only_valid_sources(self):
        def eia(key):
            if key != "wti":
                raise OSError("test outage")
            return self.frame()
        with temporary() as folder:
            data = Path(folder)
            with patch("fetch.fetch_eia", side_effect=eia), patch("fetch.fetch_cftc", side_effect=OSError("test outage")):
                self.assertEqual(refresh(data, NOW), 0)
            state = json.loads((data / "source_status.json").read_text())
            self.assertEqual(state["wti"]["last_success"], NOW.isoformat())
            self.assertEqual(state["brent"]["status"], "error")

    def test_health_distinguishes_missing_cached_and_old_data(self):
        self.assertEqual(health("wti", None, {}, NOW)["state"], "missing")
        self.assertEqual(health("wti", "2026-11-24", {}, NOW)["state"], "unverified")
        self.assertEqual(health("wti", "2026-11-01", good_sources(), NOW)["state"], "stale")
        status = good_sources()
        status["wti"]["status"] = "error"
        self.assertEqual(health("wti", "2026-11-24", status, NOW)["state"], "cached")


class IntradayTests(unittest.TestCase):
    def bars(self, date="2026-11-25"):
        times = pd.date_range(date + " 08:30", periods=15, freq="5min", tz="America/New_York")
        return pd.DataFrame({"open": np.arange(15.) + 80, "close": np.arange(15.) + 81}, index=times)

    def test_signal_waits_for_completed_anchor_and_next_bar(self):
        bars = self.bars()
        result = opening_ema(bars)
        self.assertEqual(len(result), 1)
        self.assertIn("09:35:00-05:00", result[0]["entry_time"])
        self.assertEqual(result[0]["signal_time"], result[0]["entry_time"])
        self.assertEqual(result[0]["entry_open"], bars.iloc[13].open)
        self.assertEqual(opening_ema(bars.iloc[:13]), [])

    def test_dst_and_utc_input_use_new_york_anchor(self):
        bars = self.bars("2026-07-15").tz_convert("UTC")
        self.assertIn("09:35:00-04:00", opening_ema(bars)[0]["entry_time"])

    def test_naive_duplicates_nonfinite_and_misalignment_rejected(self):
        bars = self.bars()
        for frame in (bars.tz_localize(None), pd.concat([bars, bars.iloc[:1]]), bars.set_axis(bars.index + pd.Timedelta(minutes=1)), bars.assign(close=np.nan)):
            with self.assertRaises(ValueError):
                opening_ema(frame)

    def test_gaps_and_future_bars_do_not_create_false_entries(self):
        bars = self.bars()
        self.assertEqual(opening_ema(bars.drop(bars.index[13])), [])
        self.assertEqual(opening_ema(bars.drop(bars.index[5])), [])
        before = opening_ema(bars)
        bars.iloc[14, bars.columns.get_loc("close")] = -10000
        self.assertEqual(before, opening_ema(bars))


if __name__ == "__main__":
    unittest.main()
