"""One-off historical weather download (rainfall etc.) for model training.
   cd backend && python -m scripts.backfill_weather --days 420"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.open_meteo import backfill_weather  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=420)
a = ap.parse_args()
with SessionLocal() as db:
    print(backfill_weather(db, get_settings().city_slug, days=a.days))
