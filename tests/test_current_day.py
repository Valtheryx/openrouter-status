import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("DATA_DIR", str(APP_DIR.parent / ".test-data"))
sys.path.insert(0, str(APP_DIR))
with patch.object(Thread, "start"):
    import app


class CurrentDayChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.temp.name) / "history.json"
        today_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
        self.today = today_date.isoformat()
        self.yesterday = (today_date - timedelta(days=1)).isoformat()
        self.write_history({
            self.yesterday: {"model-x": {"cost": 0.75, "tokens": 10, "requests": 1},
                             "model-y": {"cost": 0.25, "tokens": 5, "requests": 2}},
        })
        self.old_history_file = app.HISTORY_FILE
        self.old_hourly = app._hourly
        app.HISTORY_FILE = str(self.history_path)
        app._hourly = {
            f"{self.today}T06": {"total": 0.2, "keys": {"key-x": 0.15, "key-y": 0.05}},
            f"{self.today}T07": {"total": 0.1, "keys": {"key-x": 0.1}},
        }

    def write_history(self, daily_model, daily_key=None):
        history = {
            "daily_model": daily_model,
            "daily_key": daily_key if daily_key is not None else {
                self.yesterday: {"key-x": {"cost": 1.0, "tokens": 10, "requests": 1}}},
            "daily_workspace": {},
            "credits": {"total_credits": 80, "total_usage": 1.3},
            "updated_at": "2026-10-28T06:00:00+00:00",
        }
        self.history_path.write_text(json.dumps(history))

    def tearDown(self):
        app.HISTORY_FILE = self.old_history_file
        app._hourly = self.old_hourly
        self.temp.cleanup()

    def test_estimates_today_split_from_previous_model_mix(self):
        payload = app.build_payload()
        today = payload["daily_model"][self.today]
        self.assertEqual(set(today), {"model-x", "model-y"})
        self.assertAlmostEqual(today["model-x"]["cost"], 0.225)
        self.assertAlmostEqual(today["model-y"]["cost"], 0.075)
        self.assertTrue(today["model-x"]["est"])
        self.assertEqual(payload["today"], {"date": self.today, "estimated": True,
                                            "basis": self.yesterday})
        self.assertEqual(set(payload["daily_key"][self.today]), {"key-x", "key-y"})
        self.assertAlmostEqual(payload["monthly"][-1]["cost"], 1.3)

    def test_falls_back_to_unallocated_total_without_history_basis(self):
        self.write_history({})
        payload = app.build_payload()
        today = payload["daily_model"][self.today]
        self.assertEqual(list(today), ["__today_hourly__"])
        self.assertAlmostEqual(today["__today_hourly__"]["cost"], 0.3)
        self.assertFalse(payload["today"]["estimated"])

    def test_browser_refreshes_cached_data_so_the_bar_grows_during_the_day(self):
        html = (APP_DIR / "static" / "index.html").read_text()
        self.assertRegex(html, r"setInterval\(\(\)=>\{\s*if\(!liveBusy\) load\(\);\s*\},60000\)")

    def test_daily_chart_always_labels_the_latest_date(self):
        html = (APP_DIR / "static" / "index.html").read_text()
        self.assertIn("if(i%stepX===0 || i===days.length-1)", html)

    def test_estimated_segments_are_visually_distinguished(self):
        html = (APP_DIR / "static" / "index.html").read_text()
        self.assertIn("v.est", html)
        self.assertIn("today_est", html)

    def test_hourly_current_day_replaces_partial_api_day_without_double_counting(self):
        self.write_history({
            self.yesterday: {"model-x": {"cost": 0.75, "tokens": 10, "requests": 1}},
            self.today: {"model-x": {"cost": 0.12, "tokens": 3, "requests": 1}},
        })
        payload = app.build_payload()
        self.assertEqual(list(payload["daily_model"][self.today]), ["model-x"])
        self.assertAlmostEqual(payload["daily_model"][self.today]["model-x"]["cost"], 0.3)
        self.assertAlmostEqual(payload["monthly"][-1]["cost"], 1.05)


if __name__ == "__main__":
    unittest.main()
