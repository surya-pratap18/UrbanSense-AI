import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.datastate import as_utc, classify
from app.models import RoadSegment, TrafficObservation

INTERVAL_MIN = 15
ATTRIBUTION = "Traffic data \u00a9 TomTom"
NOTE = ("TomTom does not report when a speed was measured; observed_at is the time we received it. "
        "congestion_ratio = current speed / free-flow speed. Levels are this project's own thresholds.")
FRC_LABEL = {"FRC0": "motorway", "FRC1": "major road", "FRC2": "other major road", "FRC3": "secondary road",
             "FRC4": "local connecting road", "FRC5": "local important road", "FRC6": "local road"}


def congestion_level(ratio: float | None, closed: bool = False) -> str | None:
    if closed:
        return "closed"
    if ratio is None:
        return None
    return "free_flow" if ratio >= 0.8 else "moderate" if ratio >= 0.6 else "heavy" if ratio >= 0.4 else "severe"


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def polyline_length_m(coords: list[tuple[float, float]]) -> float:
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:]))


def thin(coords: list, max_points: int = 60) -> list:
    if len(coords) <= max_points:
        return coords
    step = math.ceil(len(coords) / max_points)
    out = coords[::step]
    return out if out[-1] == coords[-1] else out + [coords[-1]]


def segment_props(seg: RoadSegment) -> dict:
    try:
        return (json.loads(seg.geometry_geojson or "{}").get("properties") or {})
    except ValueError:
        return {}


def segment_geometry(seg: RoadSegment):
    try:
        return json.loads(seg.geometry_geojson or "{}").get("geometry")
    except ValueError:
        return None


def obs_dict(o: TrafficObservation) -> dict:
    return {"observed_at": as_utc(o.observed_at).isoformat(), "current_speed_kmh": o.current_speed_kmh,
            "free_flow_speed_kmh": o.free_flow_speed_kmh, "congestion_ratio": o.congestion_ratio,
            "congestion_level": congestion_level(o.congestion_ratio, bool(o.road_closure)),
            "travel_time_s": o.current_travel_time_s, "confidence": o.confidence, "road_closure": o.road_closure,
            "data_origin": o.data_origin}


def hotspot_ranking(db: Session, days: int = 7, limit: int = 10, now: datetime | None = None) -> list[dict]:
    """Transparent ranking (no clustering: ~20 monitored segments are too few for DBSCAN).
    score = 0.5 * (1 - mean ratio) + 0.5 * recurrence, recurrence = share of observations with ratio < 0.6."""
    now = now or datetime.now(timezone.utc)
    R = TrafficObservation.congestion_ratio
    q = select(TrafficObservation.segment_id, func.avg(R), func.count(R), func.sum(case((R < 0.6, 1), else_=0)), func.min(R)).where(
        TrafficObservation.observed_at >= now - timedelta(days=days), R.is_not(None)).group_by(TrafficObservation.segment_id)
    out = []
    for sid, mean, n, bad, worst in db.execute(q):
        seg = db.get(RoadSegment, sid)
        if seg is None or not seg.is_active:
            continue
        recurrence = (bad or 0) / n
        score = 0.5 * max(0.0, 1 - mean) + 0.5 * recurrence
        out.append({"segment_id": sid, "name": seg.name, "road_type": seg.road_type, "latitude": seg.latitude, "longitude": seg.longitude,
                    "score": round(score, 3), "mean_ratio": round(mean, 3), "worst_ratio": round(worst, 3),
                    "congested_share": round(recurrence, 3), "observations": n, "reliable": n >= 24,
                    "explanation": f"Average speed was {mean * 100:.0f}% of free-flow and {recurrence * 100:.0f}% of the {n} readings "
                                   f"were below 60% of free-flow (last {days} days)."})
    return sorted(out, key=lambda x: -x["score"])[:limit]
