"""TomTom Traffic Flow collector (flowSegmentData). Free quota: 2,500 requests/day, so: ~20 segments, 15-minute cadence,
a self-imposed daily budget guard, and fail-fast on key/quota errors (no wasted calls).
TomTom gives no measurement time: observed_at = time we received the answer (floored to the minute)."""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.http import FetchError, get_json
from app.core.config import get_settings
from app.models import City, RoadSegment, TrafficObservation
from app.services.traffic import segment_props

log = logging.getLogger("collectors.tomtom")
URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/{zoom}/json"
SOURCE = "tomtom_flow"
FATAL = ("HTTP 401", "HTTP 403", "HTTP 429")


def is_fatal(e: Exception) -> bool:
    return any(code in str(e) for code in FATAL)


def fetch_flow(lat: float, lon: float, key: str, zoom: int, *, client=None, sleep=time.sleep) -> dict:
    data = get_json(URL.format(zoom=zoom), {"key": key, "point": f"{lat},{lon}", "unit": "KMPH"}, client=client, sleep=sleep, max_attempts=2)
    d = data.get("flowSegmentData") if isinstance(data, dict) else None
    if not isinstance(d, dict):
        raise FetchError("TomTom response has no flowSegmentData")
    return d


def parse_flow(d: dict) -> dict | None:
    cs, ff = d.get("currentSpeed"), d.get("freeFlowSpeed")
    if not isinstance(cs, (int, float)) or not isinstance(ff, (int, float)) or ff <= 0 or cs < 0 or cs > 250 or ff > 250:
        return None
    conf = d.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) and 0 <= conf <= 1 else None
    tt = d.get("currentTravelTime")
    return {"current_speed_kmh": float(cs), "free_flow_speed_kmh": float(ff), "congestion_ratio": round(cs / ff, 4),
            "current_travel_time_s": float(tt) if isinstance(tt, (int, float)) and tt >= 0 else None,
            "confidence": conf, "road_closure": bool(d.get("roadClosure")), "frc": d.get("frc")}


def collect_tomtom(db: Session, city_slug: str, *, client: httpx.Client | None = None, sleep=time.sleep,
                   now: datetime | None = None, api_key: str | None = None, throttle: float = 0.25) -> int:
    s = get_settings()
    key = api_key or s.tomtom_api_key
    if not key:
        raise RuntimeError("TOMTOM_API_KEY is not set (add it to .env or the environment)")
    now = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError(f"City '{city_slug}' not found: run `python -m scripts.seed` first")
    segs = list(db.scalars(select(RoadSegment).where(RoadSegment.city_id == city.id, RoadSegment.is_active.is_(True)).order_by(RoadSegment.id)))
    if not segs:
        raise RuntimeError("No road segments configured. Run: python -m scripts.discover_segments")
    used = db.scalar(select(func.count(TrafficObservation.id)).where(TrafficObservation.source == SOURCE,
                                                                     TrafficObservation.fetched_at >= now - timedelta(hours=24))) or 0
    if used + len(segs) > s.tomtom_daily_budget:
        raise RuntimeError(f"Daily TomTom budget guard: {used} requests in the last 24 h + {len(segs)} would exceed {s.tomtom_daily_budget}")
    stored, errors = 0, []
    for seg in segs:
        zoom = int(segment_props(seg).get("zoom", s.tomtom_zoom))
        try:
            sleep(throttle)
            row = parse_flow(fetch_flow(seg.latitude, seg.longitude, key, zoom, client=client, sleep=sleep))
        except Exception as e:  # noqa: BLE001
            if is_fatal(e):
                raise RuntimeError(f"TomTom refused the request ({e}). Stopping to protect your quota.") from e
            errors.append(f"{seg.name}: {e}")
            continue
        if row is None:
            errors.append(f"{seg.name}: unusable values")
            continue
        exists = db.scalar(select(TrafficObservation.id).where(TrafficObservation.segment_id == seg.id,
                                                               TrafficObservation.observed_at == now, TrafficObservation.source == SOURCE))
        if exists:
            continue
        db.add(TrafficObservation(segment_id=seg.id, observed_at=now, fetched_at=datetime.now(timezone.utc), source=SOURCE,
                                  data_origin="OBSERVED", **{k: v for k, v in row.items() if k != "frc"}))
        stored += 1
    db.commit()
    if errors:
        log.warning("TomTom partial failures (%d): %s", len(errors), "; ".join(errors[:5]))
    if stored == 0 and errors:
        raise RuntimeError("; ".join(errors[:5]))
    return stored
