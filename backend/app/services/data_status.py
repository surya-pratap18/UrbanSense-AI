from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.datastate import as_utc, classify
from app.models import DataSourceStatus, PollutionObservation, TrafficObservation, WeatherObservation


def latest_observation_at(db: Session, source_key: str):
    """Timestamp of the newest REAL observation (not the time we last fetched). None if the source has no such notion yet."""
    if source_key == "open_meteo":
        return db.scalar(select(func.max(WeatherObservation.valid_at)).where(
            WeatherObservation.is_forecast.is_(False), WeatherObservation.valid_at <= datetime.now(timezone.utc)))
    if source_key == "openaq":
        return db.scalar(select(func.max(PollutionObservation.observed_at)).where(PollutionObservation.source == "openaq"))
    if source_key == "tomtom_traffic":
        return db.scalar(select(func.max(TrafficObservation.observed_at)))
    return None


TRACKED = {"open_meteo", "openaq", "tomtom_traffic"}


def source_rows(db: Session) -> list[dict]:
    rows = []
    for s in db.scalars(select(DataSourceStatus).order_by(DataSourceStatus.source_key)):
        newest = latest_observation_at(db, s.source_key)
        # freshness is judged by the age of the newest observation, so a successful fetch of OLD data is never called LIVE
        basis = newest if s.source_key in TRACKED else s.last_success_at
        state = classify(basis, s.expected_interval_min)
        rows.append({
            "source_key": s.source_key,
            "display_name": s.display_name,
            "state": state.value,
            "expected_interval_min": s.expected_interval_min,
            "latest_observation_at": as_utc(newest).isoformat() if newest else None,
            "last_attempt_at": as_utc(s.last_attempt_at).isoformat() if s.last_attempt_at else None,
            "last_success_at": as_utc(s.last_success_at).isoformat() if s.last_success_at else None,
            "consecutive_failures": s.consecutive_failures,
            "last_error": s.last_error,
            "records_last_run": s.records_last_run,
            "attribution": s.attribution,
        })
    return rows
