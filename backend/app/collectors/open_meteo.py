"""Open-Meteo weather collector (no API key).
NOTE: values are model-based estimates for the grid cell, not readings from a weather station.
Past hours (<= now) are stored as is_forecast=False; future hours as is_forecast=True and are
overwritten on every run (a forecast for a given hour is replaced by newer ones)."""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.http import get_json
from app.core.datastate import as_utc
from app.models import City, WeatherObservation

log = logging.getLogger("collectors.open_meteo")
URL = "https://api.open-meteo.com/v1/forecast"
VARS = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m",
        "wind_direction_10m", "cloud_cover", "weather_code"]
FIELD_MAP = {"temperature_2m": "temperature_c", "relative_humidity_2m": "humidity_pct",
             "precipitation": "rainfall_mm", "wind_speed_10m": "wind_speed_kmh",
             "wind_direction_10m": "wind_direction_deg", "cloud_cover": "cloud_cover_pct",
             "weather_code": "weather_code"}
# plausible ranges: out-of-range values become None (missing), never clamped and never zero
RANGES = {"temperature_c": (-60, 60), "humidity_pct": (0, 100), "rainfall_mm": (0, 500),
          "wind_speed_kmh": (0, 400), "wind_direction_deg": (0, 360), "cloud_cover_pct": (0, 100)}

WMO = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
       80: "Light showers", 81: "Showers", 82: "Violent showers", 95: "Thunderstorm", 96: "Thunderstorm, hail",
       99: "Thunderstorm, heavy hail"}


def describe_weather_code(code: int | None) -> str | None:
    return None if code is None else WMO.get(code, f"WMO code {code}")


def _parse_ts(s: str) -> datetime | None:
    try:
        return as_utc(datetime.fromisoformat(s))
    except (ValueError, TypeError):
        return None


def _clean(field: str, v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    lo_hi = RANGES.get(field)
    if lo_hi and not (lo_hi[0] <= v <= lo_hi[1]):
        return None
    return int(v) if field == "weather_code" else v


def fetch_weather(lat: float, lon: float, *, client: httpx.Client | None = None, sleep=time.sleep) -> dict:
    params = {"latitude": lat, "longitude": lon, "current": ",".join(VARS), "hourly": ",".join(VARS),
              "past_days": 2, "forecast_days": 3, "timezone": "UTC", "wind_speed_unit": "kmh"}
    return get_json(URL, params, client=client, sleep=sleep)


def parse_weather(payload: dict, now: datetime | None = None, max_age_days: int = 100) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows, skipped, seen = [], 0, set()

    def add(ts_str, getter, is_forecast_override=None):
        nonlocal skipped
        ts = _parse_ts(ts_str)
        if ts is None or ts > now + timedelta(days=8) or ts < now - timedelta(days=max_age_days):
            skipped += 1
            return
        row = {FIELD_MAP[v]: _clean(FIELD_MAP[v], getter(v)) for v in VARS}
        row["valid_at"] = ts
        row["is_forecast"] = (ts > now) if is_forecast_override is None else is_forecast_override
        key = (ts, row["is_forecast"])
        if key in seen:      # 'current' is added first, so it wins over the hourly row for the same timestamp
            return
        seen.add(key)
        rows.append(row)

    cur = payload.get("current") or {}
    if cur.get("time"):
        add(cur["time"], lambda v: cur.get(v), is_forecast_override=False)
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    for i, t in enumerate(times):
        add(t, lambda v, i=i: (h.get(v) or [])[i] if i < len(h.get(v) or []) else None)
    if skipped:
        log.warning("Skipped %d weather rows with invalid/out-of-window timestamps", skipped)
    return rows


def store_weather(db: Session, city: City, rows: list[dict], source: str = "open_meteo") -> dict:
    """Upsert by (city, valid_at, is_forecast, source): no duplicates, forecasts get refreshed."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    lo, hi = min(r["valid_at"] for r in rows), max(r["valid_at"] for r in rows)
    existing = {}
    for o in db.scalars(select(WeatherObservation).where(
            WeatherObservation.city_id == city.id, WeatherObservation.source == source,
            WeatherObservation.valid_at >= lo, WeatherObservation.valid_at <= hi)):
        existing[(as_utc(o.valid_at), o.is_forecast)] = o
    ins = upd = 0
    for r in rows:
        key = (r["valid_at"], r["is_forecast"])
        obj = existing.get(key)
        values = {k: r[k] for k in FIELD_MAP.values()}
        if obj:
            if any(getattr(obj, k) != v for k, v in values.items()):
                for k, v in values.items():
                    setattr(obj, k, v)
                obj.fetched_at = datetime.now(timezone.utc)
                upd += 1
        else:
            db.add(WeatherObservation(city_id=city.id, valid_at=r["valid_at"], is_forecast=r["is_forecast"],
                                      latitude=city.latitude, longitude=city.longitude, source=source, **values))
            ins += 1
    db.commit()
    return {"inserted": ins, "updated": upd}


def collect_weather(db: Session, city_slug: str, *, client: httpx.Client | None = None, sleep=time.sleep,
                    now: datetime | None = None) -> int:
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError(f"City '{city_slug}' not found: run `python -m scripts.seed` first")
    payload = fetch_weather(city.latitude, city.longitude, client=client, sleep=sleep)
    rows = parse_weather(payload, now=now)
    if not rows:
        raise RuntimeError("Open-Meteo returned no usable rows")
    res = store_weather(db, city, rows)
    log.info("Weather stored: %s", res)
    return res["inserted"] + res["updated"]


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def backfill_weather(db: Session, city_slug: str, days: int = 420, *, client: httpx.Client | None = None,
                     sleep=time.sleep, now: datetime | None = None) -> dict:
    """Historical hourly weather for model training (rainfall etc.).
    Old part from the ERA5-based archive API (stored as source 'open_meteo_archive'); the last ~8 days, which the
    archive does not cover yet, come from the normal API (source 'open_meteo'). Re-run safely at any time."""
    now = now or datetime.now(timezone.utc)
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError("City not found: run scripts.seed first")
    start = (now - timedelta(days=days)).date()
    end = (now - timedelta(days=8)).date()
    arch = get_json(ARCHIVE_URL, {"latitude": city.latitude, "longitude": city.longitude, "start_date": start.isoformat(),
                                  "end_date": end.isoformat(), "hourly": ",".join(VARS), "timezone": "UTC",
                                  "wind_speed_unit": "kmh"}, client=client, sleep=sleep, timeout=60)
    rows = [r for r in parse_weather(arch, now=now, max_age_days=days + 30) if not r["is_forecast"]]
    r1 = store_weather(db, city, rows, source="open_meteo_archive")
    tail = get_json(URL, {"latitude": city.latitude, "longitude": city.longitude, "hourly": ",".join(VARS),
                          "past_days": 8, "forecast_days": 1, "timezone": "UTC", "wind_speed_unit": "kmh"},
                    client=client, sleep=sleep)
    rows2 = [r for r in parse_weather(tail, now=now) if not r["is_forecast"]]
    r2 = store_weather(db, city, rows2, source="open_meteo")
    return {"archive": r1, "recent": r2}
