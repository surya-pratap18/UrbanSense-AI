"""One-off history download from OpenAQ (resumable; safe to re-run).
   cd backend && python -m scripts.backfill_openaq --days 400
About 5-6 minutes for 2 stations x 10 sensors (deliberately slow to respect OpenAQ rate limits)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.openaq import backfill_openaq  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=400)
ap.add_argument("--include-cuttack", action="store_true")
a = ap.parse_args()
with SessionLocal() as db:
    n = backfill_openaq(db, get_settings().city_slug, days=a.days, include_cuttack=a.include_cuttack or None)
print("Done. Hourly rows stored/updated:", n)
