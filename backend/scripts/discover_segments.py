"""Choose which road segments to monitor (run ONCE; uses up to ~80 of your 2,500 daily TomTom requests).
   cd backend
   python -m scripts.discover_segments --probe                 # compares zoom levels with 9 requests, saves nothing
   python -m scripts.discover_segments --zoom 12 --dry-run     # preview the selection
   python -m scripts.discover_segments --zoom 12               # save ~20 segments
Needs internet access to overpass-api.de (OpenStreetMap) and TOMTOM_API_KEY in .env."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.overpass import build_candidates, fetch_roads  # noqa: E402
from app.collectors.tomtom import fetch_flow  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.services.segment_discovery import describe_flow, discover  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--zoom", type=int, default=None)
ap.add_argument("--keep", type=int, default=20)
ap.add_argument("--max-candidates", type=int, default=80)
ap.add_argument("--min-length", type=float, default=300, help="metres; drops tiny pieces such as short flyovers")
ap.add_argument("--max-length", type=float, default=6000, help="metres; very long segments hide local jams")
ap.add_argument("--exclude", nargs="*", default=["Service Road"], help="generic road names to ignore")
ap.add_argument("--refresh-roads", action="store_true", help="ignore the cached OpenStreetMap roads and download again")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--probe", action="store_true")
a = ap.parse_args()
s = get_settings()
if not s.tomtom_api_key:
    sys.exit("TOMTOM_API_KEY missing in .env")
if a.probe:
    cands = build_candidates(fetch_roads(refresh=a.refresh_roads), 40)
    pts = [cands[0], cands[len(cands) // 2], cands[-1]]
    print("zoom | road | FRC | segment length (km)")
    for z in (10, 12, 14):
        for c in pts:
            d = describe_flow(fetch_flow(c["lat"], c["lon"], s.tomtom_api_key, z))
            print(f"{z:4d} | {c['name'][:30]:30s} | {d['frc'] if d else '-'} | {d['length_m'] / 1000 if d else 0:.2f}")
    print("Prefer the zoom whose segments are about 0.3-3 km long, then run with --zoom N")
    sys.exit(0)
with SessionLocal() as db:
    print(discover(db, s.city_slug, s.tomtom_api_key, zoom=a.zoom or s.tomtom_zoom, keep=a.keep, max_candidates=a.max_candidates, dry_run=a.dry_run, refresh_roads=a.refresh_roads,
                   min_length_m=a.min_length, max_length_m=a.max_length, exclude_names=tuple(a.exclude)))
