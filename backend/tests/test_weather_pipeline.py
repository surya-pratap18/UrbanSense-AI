from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.collectors.http import FetchError, get_json
from app.collectors.open_meteo import collect_weather, parse_weather
from app.core.config import get_settings
from app.models import DataSourceStatus, WeatherObservation
from app.services import ingestion

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def payload(temp=30.0, hours_back=3, hours_ahead=3):
    times = [NOW + timedelta(hours=h) for h in range(-hours_back, hours_ahead + 1)]
    n = len(times)
    return {
        "current": {"time": iso(NOW), "interval": 900, "temperature_2m": temp, "relative_humidity_2m": 70,
                    "precipitation": 0.0, "wind_speed_10m": 9.5, "wind_direction_10m": 180, "cloud_cover": 40, "weather_code": 2},
        "hourly": {"time": [iso(t) for t in times], "temperature_2m": [temp] * n, "relative_humidity_2m": [70] * n,
                   "precipitation": [0.0] * n, "wind_speed_10m": [9.5] * n, "wind_direction_10m": [180] * n,
                   "cloud_cover": [40] * n, "weather_code": [2] * n},
    }


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------- HTTP retry behaviour ----------
def test_retry_then_success():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(500) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    sleeps = []
    assert get_json("http://x", client=mock_client(h), sleep=sleeps.append) == {"ok": 1}
    assert len(calls) == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0] * 1.2  # exponential growth


def test_gives_up_after_max_attempts():
    with pytest.raises(FetchError, match="after 3 attempts"):
        get_json("http://x", client=mock_client(lambda r: httpx.Response(503)), sleep=lambda s: None)


def test_no_retry_on_permanent_4xx():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(400, text="bad")

    with pytest.raises(FetchError, match="HTTP 400"):
        get_json("http://x", client=mock_client(h), sleep=lambda s: None)
    assert len(calls) == 1


def test_timeout_is_retried():
    def h(req):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(FetchError, match="ConnectTimeout"):
        get_json("http://x", client=mock_client(h), sleep=lambda s: None)


def test_retry_after_header_is_honoured():
    seq = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})]
    sleeps = []
    get_json("http://x", client=mock_client(lambda r: seq.pop(0)), sleep=sleeps.append)
    assert 7 <= sleeps[0] <= 7 * 1.25


# ---------- parsing / validation ----------
def test_parse_splits_observed_and_forecast_and_keeps_nulls():
    p = payload()
    p["hourly"]["temperature_2m"][0] = None             # missing -> None, not 0
    p["hourly"]["relative_humidity_2m"][1] = 140        # impossible -> None
    rows = parse_weather(p, now=NOW + timedelta(minutes=30))
    first = [r for r in rows if r["valid_at"] == NOW - timedelta(hours=3)][0]
    assert first["temperature_c"] is None
    second = [r for r in rows if r["valid_at"] == NOW - timedelta(hours=2)][0]
    assert second["humidity_pct"] is None
    assert any(r["is_forecast"] for r in rows) and any(not r["is_forecast"] for r in rows)


def test_parse_skips_bad_timestamps():
    p = payload()
    p["hourly"]["time"][0] = "not-a-date"
    p["hourly"]["time"][1] = iso(NOW + timedelta(days=60))
    rows = parse_weather(p, now=NOW)
    assert all(isinstance(r["valid_at"], datetime) for r in rows)
    assert len(rows) == len(payload()["hourly"]["time"]) - 2   # 'current' merges into the same-hour row


# ---------- storage: dedupe + update ----------
def test_store_is_idempotent_and_updates_forecasts(db):
    client = mock_client(lambda r: httpx.Response(200, json=payload(temp=30)))
    n1 = collect_weather(db, "bhubaneswar", client=client, now=NOW)
    total = db.scalar(select(func.count(WeatherObservation.id)))
    assert n1 == total > 0
    n2 = collect_weather(db, "bhubaneswar", client=client, now=NOW)       # identical data again
    assert n2 == 0 and db.scalar(select(func.count(WeatherObservation.id))) == total
    client2 = mock_client(lambda r: httpx.Response(200, json=payload(temp=33)))
    n3 = collect_weather(db, "bhubaneswar", client=client2, now=NOW)       # changed values -> updated, not duplicated
    assert n3 > 0 and db.scalar(select(func.count(WeatherObservation.id))) == total


# ---------- ingestion service + status ----------
def test_run_collector_records_success_and_failure(db, monkeypatch):
    monkeypatch.setitem(ingestion.COLLECTORS, "weather", ("open_meteo", lambda d: 5))
    assert ingestion.run_collector(db, "weather") == {"ok": True, "source": "open_meteo", "records": 5}
    st = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == "open_meteo"))
    assert st.last_success_at is not None and st.consecutive_failures == 0

    def boom(d):
        raise FetchError("down")

    monkeypatch.setitem(ingestion.COLLECTORS, "weather", ("open_meteo", boom))
    res = ingestion.run_collector(db, "weather")
    db.refresh(st)
    assert res["ok"] is False and st.consecutive_failures == 1 and "down" in st.last_error
    assert st.last_success_at is not None            # previous success time preserved (not overwritten)


# ---------- API ----------
def test_weather_endpoints_before_and_after_collection(client, db):
    r = client.get("/api/weather/current").json()
    assert r["data"] is None and r["meta"]["data_state"] == "UNAVAILABLE"
    collect_weather(db, "bhubaneswar", client=mock_client(lambda q: httpx.Response(200, json=payload())), now=NOW + timedelta(minutes=5))
    cur = client.get("/api/weather/current").json()
    assert cur["data"]["temperature_c"] == 30.0 and cur["meta"]["data_state"] == "LIVE"
    assert cur["data"]["condition"] == "Partly cloudy"
    fc = client.get("/api/weather/forecast?hours=6").json()
    assert fc["meta"]["count"] >= 1 and all(x["is_forecast"] for x in fc["data"])
    assert client.get("/api/weather/forecast?hours=500").status_code == 422


def test_ingest_endpoint_security_and_cooldown(client, db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "cron_secret", "topsecret")
    monkeypatch.setitem(ingestion.COLLECTORS, "weather", ("open_meteo", lambda d: 3))
    assert client.post("/api/ingest/weather").status_code == 401
    assert client.post("/api/ingest/weather", headers={"X-Cron-Secret": "wrong"}).status_code == 401
    assert client.post("/api/ingest/weather", headers={"X-Cron-Secret": "topsecret"}).json()["data"]["records"] == 3
    assert client.post("/api/ingest/weather", headers={"X-Cron-Secret": "topsecret"}).status_code == 200   # cron: no cooldown
    client.post("/api/auth/register", json={"email": "u@x.com", "password": "password123"})
    ut = client.post("/api/auth/login", json={"email": "u@x.com", "password": "password123"}).json()["access_token"]
    assert client.post("/api/ingest/weather", headers={"Authorization": f"Bearer {ut}"}).status_code == 403
    at = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpass1"}).json()["access_token"]
    r = client.post("/api/ingest/weather", headers={"Authorization": f"Bearer {at}"})
    assert r.status_code == 429 and "Retry-After" in r.headers            # just ran via cron -> admin hits cooldown
    assert client.post("/api/ingest/nonsense", headers={"X-Cron-Secret": "topsecret"}).status_code == 404
