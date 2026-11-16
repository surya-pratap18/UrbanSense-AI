from datetime import datetime, timedelta, timezone

from app.models import Location, PollutionObservation

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def seed_station(db, hours=30, age_hours=0, name="Lingraj Mandir"):
    loc = Location(city_id=1, kind="aq_station", source="openaq", external_id="1", name=name, latitude=20.24, longitude=85.83)
    db.add(loc)
    db.commit()
    end = NOW - timedelta(hours=age_hours)
    for h in range(hours):
        t = end - timedelta(hours=h)
        for p, v, u in [("pm25", 45, "\u00b5g/m\u00b3"), ("pm10", 80, "\u00b5g/m\u00b3"), ("no2", 20, "ppb"), ("temperature", 29, "c")]:
            db.add(PollutionObservation(location_id=loc.id, observed_at=t, parameter=p, value=v, unit=u, source="openaq"))
    db.commit()
    return loc


def test_empty_state_is_honest(client):
    assert client.get("/api/pollution/stations").json()["data"] == []
    assert client.get("/api/pollution/current").json()["data"] == []
    assert client.get("/api/pollution/current?station_id=9").status_code == 404


def test_current_has_index_state_and_attribution(client, db):
    loc = seed_station(db)
    r = client.get("/api/pollution/current").json()
    s = r["data"][0]
    assert s["data_state"] == "LIVE" and s["values"]["pm25"]["value"] == 45
    assert s["station_weather"]["temperature"]["value"] == 29
    idx = s["indicative_index"]
    assert idx["valid"] and idx["index"] == 80 and idx["official"] is False and idx["dominant_pollutant"] == "pm10"
    assert "INDICATIVE" in r["meta"]["note"] and "OpenAQ" in r["meta"]["attribution"]
    assert client.get(f"/api/pollution/current?station_id={loc.id}").status_code == 200


def test_old_data_is_never_live(client, db):
    seed_station(db, age_hours=10)
    s = client.get("/api/pollution/current").json()["data"][0]
    assert s["data_state"] == "HISTORICAL"                       # 10 h old vs 60 min cadence
    st = client.get("/api/dashboard/data-status").json()["data"]
    assert {r["source_key"]: r["state"] for r in st}["openaq"] == "HISTORICAL"


def test_data_status_live_when_fresh(client, db):
    seed_station(db)
    st = {r["source_key"]: r for r in client.get("/api/dashboard/data-status").json()["data"]}
    assert st["openaq"]["state"] == "LIVE" and st["openaq"]["latest_observation_at"]


def test_stations_and_history_pagination_and_validation(client, db):
    loc = seed_station(db, hours=30)
    st = client.get("/api/pollution/stations").json()["data"][0]
    assert "pm25" in st["parameters"] and st["data_state"] == "LIVE"
    r = client.get(f"/api/pollution/history?station_id={loc.id}&parameter=pm25&page=1&page_size=10").json()
    assert len(r["data"]) == 10 and r["meta"]["total"] == 30
    times = [x["observed_at"] for x in r["data"]]
    assert times == sorted(times)
    assert client.get(f"/api/pollution/history?station_id={loc.id}&parameter=bogus").status_code == 422
    assert client.get("/api/pollution/history?station_id=999").status_code == 404
    bad = f"/api/pollution/history?station_id={loc.id}&start=2026-11-10T00:00:00Z&end=2026-11-01T00:00:00Z"
    assert client.get(bad).status_code == 422
