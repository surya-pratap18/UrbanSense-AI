from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.open_meteo import describe_weather_code
from app.core.config import get_settings
from app.core.datastate import as_utc, classify
from app.database.session import get_db
from app.models import City, WeatherObservation
from app.utils.responses import ok

router = APIRouter(prefix="/api/weather", tags=["Weather"])
INTERVAL_MIN = 60
NOTE = "Model-based estimate for the grid cell (Open-Meteo), not a weather-station measurement."
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


def _city(db: Session) -> City:
    city = db.scalar(select(City).where(City.slug == get_settings().city_slug))
    if city is None:
        raise HTTPException(503, "City not configured: run scripts/seed.py")
    return city


def _row(o: WeatherObservation) -> dict:
    return {"valid_at": as_utc(o.valid_at).isoformat(), "fetched_at": as_utc(o.fetched_at).isoformat() if o.fetched_at else None,
            "is_forecast": o.is_forecast, "latitude": o.latitude, "longitude": o.longitude,
            "temperature_c": o.temperature_c, "humidity_pct": o.humidity_pct, "rainfall_mm": o.rainfall_mm,
            "wind_speed_kmh": o.wind_speed_kmh, "wind_direction_deg": o.wind_direction_deg,
            "cloud_cover_pct": o.cloud_cover_pct, "weather_code": o.weather_code,
            "condition": describe_weather_code(o.weather_code), "source": o.source}


@router.get("/current")
def current(db: Session = Depends(get_db)):
    city = _city(db)
    now = datetime.now(timezone.utc)
    o = db.scalar(select(WeatherObservation).where(
        WeatherObservation.city_id == city.id, WeatherObservation.is_forecast.is_(False),
        WeatherObservation.valid_at <= now).order_by(WeatherObservation.valid_at.desc()).limit(1))
    state = classify(o.valid_at if o else None, INTERVAL_MIN).value
    return ok(_row(o) if o else None, city=city.name, data_state=state, note=NOTE, attribution=ATTRIBUTION)


@router.get("/forecast")
def forecast(hours: int = Query(24, ge=1, le=72), db: Session = Depends(get_db)):
    city = _city(db)
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(WeatherObservation).where(
        WeatherObservation.city_id == city.id, WeatherObservation.is_forecast.is_(True),
        WeatherObservation.valid_at > now, WeatherObservation.valid_at <= now + timedelta(hours=hours))
        .order_by(WeatherObservation.valid_at)).all()
    newest_fetch = max((as_utc(r.fetched_at) for r in rows if r.fetched_at), default=None)
    state = classify(newest_fetch, INTERVAL_MIN).value  # freshness of the forecast = when we last fetched it
    return ok([_row(r) for r in rows], city=city.name, hours=hours, count=len(rows), data_state=state,
              note=NOTE, attribution=ATTRIBUTION)
