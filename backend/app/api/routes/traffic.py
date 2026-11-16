from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.datastate import as_utc, classify
from app.database.session import get_db
from app.models import RoadSegment, TrafficObservation
from app.services.traffic import ATTRIBUTION, INTERVAL_MIN, NOTE, hotspot_ranking, obs_dict, segment_geometry, segment_props
from app.utils.responses import ok

router = APIRouter(prefix="/api/traffic", tags=["Traffic"])


def _segments(db: Session):
    return list(db.scalars(select(RoadSegment).where(RoadSegment.is_active.is_(True)).order_by(RoadSegment.id)))


@router.get("/segments")
def segments(db: Session = Depends(get_db)):
    out = [{"segment_id": s.id, "name": s.name, "road_type": s.road_type, "latitude": s.latitude, "longitude": s.longitude,
            "length_m": segment_props(s).get("length_m"), "frc": segment_props(s).get("frc_label"), "geometry": segment_geometry(s)}
           for s in _segments(db)]
    return ok(out, count=len(out), attribution=ATTRIBUTION + " | Road data \u00a9 OpenStreetMap contributors")


@router.get("/current")
def current(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    out = []
    for s in _segments(db):
        o = db.scalar(select(TrafficObservation).where(TrafficObservation.segment_id == s.id).order_by(TrafficObservation.observed_at.desc()).limit(1))
        base = {"segment_id": s.id, "name": s.name, "road_type": s.road_type, "latitude": s.latitude, "longitude": s.longitude}
        out.append({**base, "data_state": classify(o.observed_at if o else None, INTERVAL_MIN, now).value,
                    "latest": obs_dict(o) if o else None})
    return ok(out, count=len(out), attribution=ATTRIBUTION, note=NOTE)


@router.get("/history")
def history(segment_id: int = Query(..., ge=1), start: datetime | None = None, end: datetime | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    seg = db.get(RoadSegment, segment_id)
    if seg is None:
        raise HTTPException(404, "Segment not found")
    end = as_utc(end) if end else datetime.now(timezone.utc)
    start = as_utc(start) if start else end - timedelta(days=1)
    if start >= end:
        raise HTTPException(422, "start must be before end")
    q = select(TrafficObservation).where(TrafficObservation.segment_id == segment_id, TrafficObservation.observed_at > start,
                                         TrafficObservation.observed_at <= end)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(TrafficObservation.observed_at).offset((page - 1) * page_size).limit(page_size)).all()
    return ok([obs_dict(r) for r in rows], segment=seg.name, page=page, page_size=page_size, total=total, attribution=ATTRIBUTION, note=NOTE)


@router.get("/hotspots")
def hotspots(days: int = Query(7, ge=1, le=90), limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    rows = hotspot_ranking(db, days, limit)
    return ok(rows, count=len(rows), days=days, attribution=ATTRIBUTION,
              method="ranking: score = 0.5*(1 - mean speed ratio) + 0.5*share of readings below 60% of free-flow",
              note="'reliable' is true only with at least 24 readings. Rankings are descriptive, not predictions.")
