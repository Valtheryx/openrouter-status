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
        yesterday = (today_date - timedelta(days=1)).isoformat()
        history = {
            "daily_model": {yesterday: {"model-x": {"cost": 1.0, "tokens": 10, "requests": 1}}},
            "daily_key": {yesterday: {"key-x": {"cost": 1.0, "tokens": 10, "requests": 1}}},
            "daily_workspace": {},
            "credits": {"total_credits": 80, "total_usage": 1.3},
            "updated_at": "2026-10-28T06:00:00+00:00",
        }
        self.history_path.write_text(json.dumps(history))
        self.old_history_file = app.HISTORY_FILE
        self.old_hourly = app._hourly
        app.HISTORY_FILE = str(self.history_path)
        app._hourly = {
            f"{self.today}T06": {"total": 0.2, "keys": {"key-x": 0.15, "key-y": 0.05}},
            f"{self.today}T07": {"total": 0.1, "keys": {"key-x": 0.1}},
        }

    def tearDown(self):
        app.HISTORY_FILE = self.old_history_file
        app._hourly = self.old_hourly
        self.temp.cleanup()

    def test_adds_provisional_current_day_from_hourly_samples(self):
        payload = app.build_payload()
        self.assertIn(self.today, payload["daily_model"])
        self.assertAlmostEqual(payload["daily_model"][self.today]["__today_hourly__"]["cost"], 0.3)
        self.assertEqual(set(payload["daily_key"][self.today]), {"key-x", "key-y"})
        self.assertAlmostEqual(payload["monthly"][-1]["cost"], 1.3)

    def test_browser_refreshes_cached_data_so_the_bar_grows_during_the_day(self):
        html = (APP_DIR / "static" / "index.html").read_text()
        self.assertRegex(html, r"setInterval\(\(\)=>\{\s*if\(!liveBusy\) load\(\);\s*\},60000\)")

    def test_daily_chart_always_labels_the_latest_date(self):
        html = (APP_DIR / "static" / "index.html").read_text()
        self.assertIn("if(i%stepX===0 || i===days.length-1)", html)

    def test_hourly_current_day_replaces_partial_api_day_without_double_counting(self):
        history = json.loads(self.history_path.read_text())
        history["daily_model"][self.today] = {
            "model-x": {"cost": 0.12, "tokens": 3, "requests": 1}
        }
        history["daily_key"][self.today] = {
            "key-x": {"cost": 0.12, "tokens": 3, "requests": 1}
        }
        self.history_path.write_text(json.dumps(history))

        payload = app.build_payload()
        self.assertEqual(list(payload["daily_model"][self.today]), ["__today_hourly__"])
        self.assertAlmostEqual(payload["daily_model"][self.today]["__today_hourly__"]["cost"], 0.3)
        self.assertAlmostEqual(payload["monthly"][-1]["cost"], 1.3)
        self.assertAlmostEqual(payload["daily_key"][self.today]["key-x"]["cost"], 0.25)


if __name__ == "__main__":
    unittest.main()
