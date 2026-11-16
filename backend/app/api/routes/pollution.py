from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.datastate import as_utc, classify
from app.database.session import get_db
from app.models import Location, PollutionObservation
from app.services.pollution import ATTRIBUTION, INDEX_NOTE, INTERVAL_MIN, list_stations, station_snapshot
from app.utils.responses import ok

router = APIRouter(prefix="/api/pollution", tags=["Air Quality"])
PARAM_PATTERN = "^(pm25|pm10|no2|so2|co|o3|temperature|relativehumidity|wind_speed|wind_direction)$"


@router.get("/stations")
def stations(db: Session = Depends(get_db)):
    out = []
    for loc in list_stations(db):
        latest = db.scalar(select(func.max(PollutionObservation.observed_at)).where(PollutionObservation.location_id == loc.id))
        params = sorted(p for (p,) in db.execute(select(PollutionObservation.parameter).where(
            PollutionObservation.location_id == loc.id).distinct()))
        out.append({"station_id": loc.id, "name": loc.name, "latitude": loc.latitude, "longitude": loc.longitude,
                    "source": loc.source, "external_id": loc.external_id, "parameters": params,
                    "latest_observation_at": as_utc(latest).isoformat() if latest else None,
                    "data_state": classify(latest, INTERVAL_MIN).value})
    return ok(out, count=len(out), attribution=ATTRIBUTION)


@router.get("/current")
def current(station_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    locs = list_stations(db)
    if station_id is not None:
        locs = [l for l in locs if l.id == station_id]
        if not locs:
            raise HTTPException(404, "Station not found")
    now = datetime.now(timezone.utc)
    return ok([station_snapshot(db, l, now) for l in locs], count=len(locs), attribution=ATTRIBUTION, note=INDEX_NOTE)


@router.get("/history")
def history(station_id: int = Query(..., ge=1), parameter: str = Query("pm25", pattern=PARAM_PATTERN),
            start: datetime | None = None, end: datetime | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    loc = db.get(Location, station_id)
    if loc is None or loc.kind != "aq_station":
        raise HTTPException(404, "Station not found")
    end = as_utc(end) if end else datetime.now(timezone.utc)
    start = as_utc(start) if start else end - timedelta(days=7)
    if start >= end:
        raise HTTPException(422, "start must be before end")
    q = select(PollutionObservation).where(PollutionObservation.location_id == station_id,
                                           PollutionObservation.parameter == parameter,
                                           PollutionObservation.observed_at > start, PollutionObservation.observed_at <= end)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(PollutionObservation.observed_at).offset((page - 1) * page_size).limit(page_size)).all()
    data = [{"observed_at": as_utc(r.observed_at).isoformat(), "value": r.value, "unit": r.unit, "data_origin": r.data_origin} for r in rows]
    return ok(data, station=loc.name, parameter=parameter, page=page, page_size=page_size, total=total,
              start=start.isoformat(), end=end.isoformat(), attribution=ATTRIBUTION)


@router.get("/predictions")
def predictions(station_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    """Latest stored forecasts (PM2.5, PM10 at +1/+3/+6 h) with the model's honest validation summary."""
    from app.models import ModelRegistry, PollutionPrediction
    locs = list_stations(db)
    if station_id is not None:
        locs = [l for l in locs if l.id == station_id]
        if not locs:
            raise HTTPException(404, "Station not found")
    out = []
    for loc in locs:
        items, origins = [], []
        for param in ("pm25", "pm10"):
            latest = db.scalar(select(func.max(PollutionPrediction.made_at)).where(
                PollutionPrediction.location_id == loc.id, PollutionPrediction.parameter == param))
            if latest is None:
                continue
            origins.append(as_utc(latest))
            for p in db.scalars(select(PollutionPrediction).where(
                    PollutionPrediction.location_id == loc.id, PollutionPrediction.parameter == param,
                    PollutionPrediction.made_at == latest).order_by(PollutionPrediction.horizon_h)):
                reg = db.scalar(select(ModelRegistry).where(ModelRegistry.module == "pollution",
                                                            ModelRegistry.name == f"{param}_h{p.horizon_h}",
                                                            ModelRegistry.version == p.model_version))
                m = (reg.metrics or {}) if reg else {}
                items.append({"parameter": param, "horizon_h": p.horizon_h, "target_time": as_utc(p.target_time).isoformat(),
                              "predicted_value": p.predicted_value, "lower": p.lower, "upper": p.upper, "unit": "\u00b5g/m\u00b3",
                              "interval_level": (m.get("interval") or {}).get("level"), "trend": p.trend,
                              "pm_band_category": p.index_category, "model_version": p.model_version,
                              "model_status": reg.calibration_status if reg else "UNKNOWN",
                              "test_rmse": (m.get("test") or {}).get("rmse"), "skill_vs_persistence": m.get("skill_vs_persistence")})
        origin = max(origins) if origins else None
        out.append({"station_id": loc.id, "name": loc.name, "forecast_origin": origin.isoformat() if origin else None,
                    "input_data_state": classify(origin, INTERVAL_MIN).value, "forecasts": items})
    return ok(out, count=len(out), attribution=ATTRIBUTION,
              note="Machine-learning forecasts of hourly concentrations. pm_band_category compares the predicted hourly value with "
                   "CPCB PM breakpoints (indicative; not an official AQI). model_status tells you whether the model beat simple baselines on held-out data.")
