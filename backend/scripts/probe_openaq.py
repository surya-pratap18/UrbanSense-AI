"""Diagnostic: shows exactly what OpenAQ returns (never prints your key).
   cd backend && python -m scripts.probe_openaq"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.openaq import BASE, fetch_sensor_hours, _headers  # noqa: E402
from app.collectors.http import get_json  # noqa: E402
from app.core.config import get_settings  # noqa: E402

key = get_settings().openaq_api_key
if not key:
    sys.exit("OPENAQ_API_KEY missing in .env")
loc = get_json(f"{BASE}/locations/3409505", headers=_headers(key))["results"][0]
print("Station:", loc["name"], "| sensors:", [s["parameter"]["name"] for s in loc["sensors"]])
pm25 = next(s for s in loc["sensors"] if s["parameter"]["name"] == "pm25")
now = datetime.now(timezone.utc)
items = fetch_sensor_hours(pm25["id"], now - timedelta(hours=6), now, key)
print(f"Hourly rows returned for the last 6 h: {len(items)}")
print(json.dumps(items[:2], indent=2, ensure_ascii=False))
