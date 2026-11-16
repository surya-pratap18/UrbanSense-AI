from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.datastate import as_utc, classify
from app.models import Location, PollutionObservation
from app.services.aqi import compute_index

INTERVAL_MIN = 60                      # stations publish hourly averages
POLLUTANTS = ("pm25", "pm10", "no2", "so2", "co", "o3")
STATION_MET = ("temperature", "relativehumidity", "wind_speed", "wind_direction")
ATTRIBUTION = "CPCB/OSPCB monitoring data via OpenAQ (openaq.org); license per provider."
INDEX_NOTE = "CPCB-style INDICATIVE index computed from hourly data. Not an official AQI."


def station_snapshot(db: Session, loc: Location, now: datetime | None = None) -> dict:
    base = {"station_id": loc.id, "name": loc.name, "latitude": loc.latitude, "longitude": loc.longitude,
            "source": loc.source, "external_id": loc.external_id}
    latest = db.scalar(select(func.max(PollutionObservation.observed_at)).where(PollutionObservation.location_id == loc.id))
    if latest is None:
        return {**base, "data_state": "UNAVAILABLE", "latest_observation_at": None, "values": {},
                "station_weather": {}, "indicative_index": None}
    latest = as_utc(latest)
    rows = db.execute(select(PollutionObservation.parameter, PollutionObservation.observed_at, PollutionObservation.value,
                             PollutionObservation.unit).where(
        PollutionObservation.location_id == loc.id, PollutionObservation.observed_at > latest - timedelta(hours=26))
        .order_by(PollutionObservation.observed_at)).all()
    series: dict[str, list] = {}
    newest: dict[str, tuple] = {}
    for p, ts, v, u in rows:
        series.setdefault(p, []).append((as_utc(ts), v, u))
        newest[p] = (as_utc(ts), v, u)
    fmt = lambda t: {"value": t[1], "unit": t[2], "observed_at": t[0].isoformat()}  # noqa: E731
    return {**base, "data_state": classify(latest, INTERVAL_MIN, now).value, "latest_observation_at": latest.isoformat(),
            "values": {p: fmt(newest[p]) for p in POLLUTANTS if p in newest},
            "station_weather": {p: fmt(newest[p]) for p in STATION_MET if p in newest},
            "indicative_index": compute_index({p: series[p] for p in POLLUTANTS if p in series}, latest)}


def list_stations(db: Session) -> list[Location]:
    return list(db.scalars(select(Location).where(Location.kind == "aq_station").order_by(Location.name)))
