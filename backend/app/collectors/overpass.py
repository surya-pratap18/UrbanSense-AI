"""Finds real, named major roads of Bhubaneswar from OpenStreetMap (Overpass API, plain HTTP: no GeoPandas/OSMnx needed).
Data \u00a9 OpenStreetMap contributors (ODbL)."""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.collectors.http import FetchError, get_json
from app.services.traffic import haversine_m

log = logging.getLogger("collectors.overpass")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ENDPOINTS = [OVERPASS_URL, "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]  # public mirrors
CACHE_PATH = Path(__file__).resolve().parents[3] / "datasets" / "external" / "overpass_roads.json"
BBOX = (20.20, 85.74, 20.38, 85.92)  # south, west, north, east: approximate Bhubaneswar urban area
HW_RANK = {"trunk": 0, "primary": 1, "secondary": 2}
HEADERS = {"User-Agent": "UrbanSenseAI-college-project/1.0"}


def fetch_roads(bbox=BBOX, *, client=None, sleep=time.sleep, cache_path: Path | None = CACHE_PATH, refresh: bool = False) -> list[dict]:
    """Roads from a local cache if present (reproducible, no network); otherwise try each Overpass server in turn and cache the result."""
    if cache_path and Path(cache_path).exists() and not refresh:
        try:
            cached = json.loads(Path(cache_path).read_text())
            if cached.get("bbox") == list(bbox):
                log.info("Using cached roads from %s (fetched %s)", cache_path, cached.get("fetched_at"))
                return cached["elements"]
        except (ValueError, KeyError):
            pass
    s, w, n, e = bbox
    q = f'[out:json][timeout:60];way["highway"~"^(trunk|primary|secondary)$"]["name"]({s},{w},{n},{e});out center tags;'
    errors = []
    for url in ENDPOINTS:
        try:
            data = get_json(url, {"data": q}, headers=HEADERS, client=client, sleep=sleep, timeout=90, max_attempts=2, base_delay=3)
        except FetchError as err:
            errors.append(str(err))
            continue
        elements = data.get("elements", []) if isinstance(data, dict) else []
        if elements and cache_path:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps({"bbox": list(bbox), "fetched_at": datetime.now(timezone.utc).isoformat(),
                                                    "attribution": "\u00a9 OpenStreetMap contributors (ODbL)", "elements": elements}))
        if elements:
            return elements
        errors.append(f"{url}: returned no roads")
    raise FetchError("All Overpass servers failed (they are free and often busy). Wait a few minutes and retry. Details: " + " | ".join(errors))


def _spread(items: list[dict], k: int, min_gap_m: float = 600) -> list[dict]:
    chosen = [items[0]]
    while len(chosen) < k:
        best, best_d = None, 0.0
        for it in items:
            d = min(haversine_m(it["lat"], it["lon"], c["lat"], c["lon"]) for c in chosen)
            if d > best_d:
                best, best_d = it, d
        if best is None or best_d < min_gap_m:
            break
        chosen.append(best)
    return chosen


def build_candidates(elements: list[dict], max_candidates: int = 80, per_name: int = 3) -> list[dict]:
    by_name: dict[str, list[dict]] = {}
    for e in elements:
        tags, c = e.get("tags") or {}, e.get("center")
        name, hw = tags.get("name"), tags.get("highway")
        if name and hw in HW_RANK and c:
            by_name.setdefault(name, []).append({"name": name, "highway": hw, "lat": c["lat"], "lon": c["lon"], "osm_id": str(e.get("id"))})
    picks = []
    for items in by_name.values():
        items.sort(key=lambda x: (x["lat"], x["lon"]))
        picks.extend(_spread(items, per_name))
    picks.sort(key=lambda c: (HW_RANK[c["highway"]], c["name"], c["lat"]))
    return picks[:max_candidates]
