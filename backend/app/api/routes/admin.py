from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.database.session import get_db
from app.models import (ModelRegistry, RoadSegment, PollutionObservation, TrafficObservation, User, WasteRecord,
                        WeatherObservation)
from pydantic import BaseModel

from app.schemas.auth import UserOut
from app.services.traffic import segment_props
from app.services.data_status import source_rows
from app.utils.responses import ok

router = APIRouter(prefix="/api/admin", tags=["Administration"], dependencies=[Depends(require_admin)])


@router.get("/data-sources")
def data_sources(db: Session = Depends(get_db)):
    return ok(source_rows(db))


@router.get("/system-health")
def system_health(db: Session = Depends(get_db)):
    counts = {
        "traffic_observations": db.scalar(select(func.count(TrafficObservation.id))),
        "pollution_observations": db.scalar(select(func.count(PollutionObservation.id))),
        "weather_observations": db.scalar(select(func.count(WeatherObservation.id))),
        "waste_records": db.scalar(select(func.count(WasteRecord.id))),
        "users": db.scalar(select(func.count(User.id))),
        "active_models": db.scalar(select(func.count(ModelRegistry.id)).where(ModelRegistry.is_active.is_(True))),
    }
    return ok({"database": "ok", "row_counts": counts, "sources": source_rows(db)})


@router.get("/users")
def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(User.id)))
    rows = db.scalars(select(User).order_by(User.id).offset((page - 1) * page_size).limit(page_size)).all()
    return ok([UserOut.model_validate(u).model_dump(mode="json") for u in rows],
              page=page, page_size=page_size, total=total)


class SegmentPatch(BaseModel):
    is_active: bool


@router.get("/segments")
def admin_segments(db: Session = Depends(get_db)):
    """All monitored road segments including switched-off ones."""
    rows = db.scalars(select(RoadSegment).order_by(RoadSegment.id)).all()
    return ok([{"segment_id": s.id, "name": s.name, "road_type": s.road_type, "is_active": s.is_active,
                "frc": segment_props(s).get("frc"), "length_m": segment_props(s).get("length_m")} for s in rows], count=len(rows))


@router.patch("/segments/{segment_id}")
def patch_segment(segment_id: int, body: SegmentPatch, db: Session = Depends(get_db)):
    """Switch a segment on/off (an off segment is no longer queried, which also saves TomTom quota). History is kept."""
    s = db.get(RoadSegment, segment_id)
    if s is None:
        raise HTTPException(404, "Segment not found")
    s.is_active = body.is_active
    db.commit()
    return ok({"segment_id": s.id, "name": s.name, "is_active": s.is_active})
