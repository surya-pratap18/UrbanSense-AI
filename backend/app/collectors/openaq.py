"""OpenAQ v3 collector for the CPCB/OSPCB stations in Bhubaneswar.
Uses /v3/locations/{id} (sensor list) and /v3/sensors/{id}/hours (hourly averages).
observed_at = END of the hourly averaging window (a value is only 'known' once the hour is over: no leakage).
Rows with <75% hourly coverage, impossible values or invalid timestamps are skipped (treated as missing, never 0)."""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.http import get_json
from app.core.config import get_settings
from app.core.datastate import as_utc
from app.models import City, Location, PollutionObservation

log = logging.getLogger("collectors.openaq")
BASE = "https://api.openaq.org/v3"
BHUBANESWAR_STATION_IDS = [3409505, 3409508]   # Lingraj Mandir, Patia (OSPCB / CPCB)
CUTTACK_STATION_IDS = [3409506]                # CDA Area, Cuttack: different city, off by default
WANTED = {"pm25", "pm10", "no2", "so2", "co", "o3", "temperature", "relativehumidity", "wind_speed", "wind_direction"}
MIN_COVERAGE_PCT = 75.0
LICENSE_NOTE = "CPCB/OSPCB data via OpenAQ; see docs.openaq.org/about/about"
RANGES = {"pm25": (0, 1500), "pm10": (0, 3000), "no2": (0, 2000), "so2": (0, 2000), "co": (0, 100000), "o3": (0, 1500),
          "temperature": (-10, 60), "relativehumidity": (0, 100), "wind_speed": (0, 60), "wind_direction": (0, 360)}


def _utc(d) -> datetime | None:
    s = d.get("utc") if isinstance(d, dict) else d
    if not s or not isinstance(s, str):
        return None
    try:
        return as_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_hour_item(item: dict, fallback_param: str | None = None, fallback_unit: str | None = None,
                    now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    value = item.get("value")
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    period = item.get("period") or {}
    end = _utc(period.get("datetimeTo"))
    if end is None:
        start = _utc(period.get("datetimeFrom"))
        end = start + timedelta(hours=1) if start else _utc(item.get("datetime"))
    if end is None or end > now + timedelta(hours=1) or end < now - timedelta(days=800):
        return None
    cov = (item.get("coverage") or {}).get("percentComplete")
    if isinstance(cov, (int, float)) and cov < MIN_COVERAGE_PCT:
        return None
    p = item.get("parameter")
    name = (p.get("name") if isinstance(p, dict) else None) or fallback_param
    unit = (p.get("units") if isinstance(p, dict) else None) or fallback_unit
    if name not in WANTED:
        return None
    lo, hi = RANGES[name]
    if not (lo <= value <= hi):
        return None
    return {"observed_at": end, "parameter": name, "value": value, "unit": unit}


def _headers(key: str) -> dict:
    return {"X-API-Key": key}


def fetch_location(station_id: int, key: str, *, client=None, sleep=time.sleep) -> dict:
    data = get_json(f"{BASE}/locations/{station_id}", headers=_headers(key), client=client, sleep=sleep)
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        raise RuntimeError(f"OpenAQ location {station_id} not found")
    return results[0]


def fetch_sensor_hours(sensor_id: int, dt_from: datetime, dt_to: datetime, key: str, *, client=None, sleep=time.sleep,
                       limit: int = 1000, max_pages: int = 10) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        params = {"datetime_from": dt_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "datetime_to": dt_to.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": limit, "page": page}
        data = get_json(f"{BASE}/sensors/{sensor_id}/hours", params, headers=_headers(key), client=client, sleep=sleep)
        results = data.get("results", []) if isinstance(data, dict) else []
        out.extend(results)
        if len(results) < limit:
            break
    return out


def sync_station(db: Session, city: City, loc: dict) -> Location:
    ext = str(loc["id"])
    row = db.scalar(select(Location).where(Location.source == "openaq", Location.external_id == ext))
    coords = loc.get("coordinates") or {}
    if row is None:
        row = Location(city_id=city.id, kind="aq_station", source="openaq", external_id=ext, name=loc.get("name") or ext,
                       latitude=coords.get("latitude"), longitude=coords.get("longitude"))
        db.add(row)
    else:
        row.name = loc.get("name") or row.name
        if coords.get("latitude") is not None:
            row.latitude, row.longitude = coords["latitude"], coords["longitude"]
    db.commit()
    db.refresh(row)
    return row


def store_observations(db: Session, location: Location, rows: list[dict]) -> dict:
    """Upsert by (location, observed_at, parameter, source): no duplicates; revised values are updated."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    ins = upd = 0
    by_param: dict[str, list[dict]] = {}
    for r in rows:
        by_param.setdefault(r["parameter"], []).append(r)
    for param, prs in by_param.items():
        lo, hi = min(r["observed_at"] for r in prs), max(r["observed_at"] for r in prs)
        existing = {as_utc(o.observed_at): o for o in db.scalars(select(PollutionObservation).where(
            PollutionObservation.location_id == location.id, PollutionObservation.parameter == param,
            PollutionObservation.source == "openaq", PollutionObservation.observed_at >= lo, PollutionObservation.observed_at <= hi))}
        seen = set()
        for r in prs:
            if r["observed_at"] in seen:
                continue
            seen.add(r["observed_at"])
            o = existing.get(r["observed_at"])
            if o:
                if o.value != r["value"]:
                    o.value, o.unit = r["value"], r["unit"]
                    upd += 1
            else:
                db.add(PollutionObservation(location_id=location.id, observed_at=r["observed_at"], parameter=param,
                                            value=r["value"], unit=r["unit"], source="openaq", license=LICENSE_NOTE,
                                            data_origin="OBSERVED"))
                ins += 1
    db.commit()
    return {"inserted": ins, "updated": upd}


def _station_ids(include_cuttack: bool | None) -> list[int]:
    inc = get_settings().openaq_include_cuttack if include_cuttack is None else include_cuttack
    return BHUBANESWAR_STATION_IDS + (CUTTACK_STATION_IDS if inc else [])


def _require_key(api_key: str | None) -> str:
    key = api_key or get_settings().openaq_api_key
    if not key:
        raise RuntimeError("OPENAQ_API_KEY is not set (add it to .env or the environment)")
    return key


def collect_openaq(db: Session, city_slug: str, *, client: httpx.Client | None = None, sleep=time.sleep,
                   now: datetime | None = None, lookback_hours: int = 48, throttle: float = 0.4,
                   include_cuttack: bool | None = None, api_key: str | None = None) -> int:
    """Regular run: fetch hours since the last stored value (minus a 3 h overlap to catch revisions)."""
    key = _require_key(api_key)
    now = now or datetime.now(timezone.utc)
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError(f"City '{city_slug}' not found: run `python -m scripts.seed` first")
    total, errors, ok_stations = 0, [], 0
    for sid in _station_ids(include_cuttack):
        try:
            loc_json = fetch_location(sid, key, client=client, sleep=sleep)
            loc = sync_station(db, city, loc_json)
            for s in loc_json.get("sensors", []):
                param = (s.get("parameter") or {}).get("name")
                if param not in WANTED:
                    continue
                last = db.scalar(select(func.max(PollutionObservation.observed_at)).where(
                    PollutionObservation.location_id == loc.id, PollutionObservation.parameter == param))
                dt_from = max(as_utc(last) - timedelta(hours=3), now - timedelta(hours=lookback_hours * 10)) if last \
                    else now - timedelta(hours=lookback_hours)
                sleep(throttle)
                items = fetch_sensor_hours(s["id"], dt_from, now, key, client=client, sleep=sleep)
                rows = [r for it in items if (r := parse_hour_item(it, param, (s.get("parameter") or {}).get("units"), now))]
                res = store_observations(db, loc, rows)
                total += res["inserted"] + res["updated"]
            ok_stations += 1
        except Exception as e:  # noqa: BLE001: one failing station must not hide the others
            db.rollback()
            errors.append(f"station {sid}: {type(e).__name__}: {e}")
            log.error("OpenAQ station %s failed: %s", sid, e)
    if ok_stations == 0:
        raise RuntimeError("; ".join(errors) or "no stations configured")
    if errors:
        log.warning("Partial OpenAQ failure: %s", "; ".join(errors))
    return total


def backfill_openaq(db: Session, city_slug: str, days: int = 400, *, client=None, sleep=time.sleep, now: datetime | None = None,
                    throttle: float = 1.1, chunk_days: int = 30, include_cuttack: bool | None = None,
                    api_key: str | None = None, progress=print) -> int:
    """One-off history download (resumable: re-running only adds what is missing)."""
    key = _require_key(api_key)
    now = now or datetime.now(timezone.utc)
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError("City not found: run scripts.seed first")
    total = 0
    for sid in _station_ids(include_cuttack):
        loc_json = fetch_location(sid, key, client=client, sleep=sleep)
        loc = sync_station(db, city, loc_json)
        first = _utc((loc_json.get("datetimeFirst") or {}))
        start_all = max(now - timedelta(days=days), first) if first else now - timedelta(days=days)
        for s in loc_json.get("sensors", []):
            param = (s.get("parameter") or {}).get("name")
            if param not in WANTED:
                continue
            unit = (s.get("parameter") or {}).get("units")
            cur, n_sensor = start_all, 0
            while cur < now:
                nxt = min(cur + timedelta(days=chunk_days), now)
                sleep(throttle)
                items = fetch_sensor_hours(s["id"], cur, nxt, key, client=client, sleep=sleep)
                rows = [r for it in items if (r := parse_hour_item(it, param, unit, now))]
                res = store_observations(db, loc, rows)
                n_sensor += res["inserted"] + res["updated"]
                cur = nxt
            total += n_sensor
            progress(f"{loc.name} / {param}: {n_sensor} hourly rows")
    return total
