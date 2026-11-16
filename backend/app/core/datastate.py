"""Data-state classification: the app must never call stale data 'live'.

States
  LIVE        newest observation is within 1.5x the source's expected update interval
  DELAYED     older than that, but within 6x the interval (source slow or a missed run)
  HISTORICAL  older than 6x the interval (real data, but not current)
  SIMULATED   generated demonstration data (always wins over age)
  UNAVAILABLE no observation has ever been received
"""
from datetime import datetime, timezone
from enum import Enum


class DataState(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    HISTORICAL = "HISTORICAL"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


LIVE_FACTOR = 1.5
DELAYED_FACTOR = 6.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC (SQLite drops tzinfo)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def classify(last_observation_at: datetime | None, expected_interval_min: float | None,
             now: datetime | None = None, simulated: bool = False) -> DataState:
    if simulated:
        return DataState.SIMULATED
    if last_observation_at is None:
        return DataState.UNAVAILABLE
    if not expected_interval_min:  # manual/imported sources have no cadence
        return DataState.HISTORICAL
    now = now or utcnow()
    age_min = (now - as_utc(last_observation_at)).total_seconds() / 60
    if age_min <= expected_interval_min * LIVE_FACTOR:
        return DataState.LIVE
    if age_min <= expected_interval_min * DELAYED_FACTOR:
        return DataState.DELAYED
    return DataState.HISTORICAL
