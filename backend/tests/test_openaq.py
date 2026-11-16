from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.collectors import openaq
from app.collectors.http import FetchError
from app.collectors.openaq import backfill_openaq, collect_openaq, parse_hour_item
from app.models import DataSourceStatus, Location, PollutionObservation
from app.services import ingestion

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
PARAMS = [("pm25", "\u00b5g/m\u00b3"), ("pm10", "\u00b5g/m\u00b3"), ("no2", "ppb"), ("so2", "ppb"), ("co", "ppb"),
          ("o3", "\u00b5g/m\u00b3"), ("temperature", "c"), ("relativehumidity", "%"), ("wind_speed", "m/s"),
          ("wind_direction", "deg"), ("no", "ppb"), ("nox", "ppb")]


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def location_json(station_id):
    return {"id": station_id, "name": f"Station {station_id}", "coordinates": {"latitude": 20.3, "longitude": 85.8},
            "datetimeFirst": {"utc": iso(NOW - timedelta(days=100))},
            "sensors": [{"id": station_id * 100 + i, "parameter": {"id": i, "name": n, "units": u}} for i, (n, u) in enumerate(PARAMS)]}


def hour_item(end, value=50.0, coverage=100):
    return {"value": value, "period": {"label": "hour", "datetimeFrom": {"utc": iso(end - timedelta(hours=1))},
                                       "datetimeTo": {"utc": iso(end)}}, "coverage": {"percentComplete": coverage}}


def make_client(hours=3, record=None):
    def handler(req: httpx.Request):
        if record is not None:
            record.append(req)
        assert req.headers.get("x-api-key") == "k"
        path = req.url.path
        if path.startswith("/v3/locations/"):
            return httpx.Response(200, json={"results": [location_json(int(path.rsplit("/", 1)[1]))]})
        if "/sensors/" in path and path.endswith("/hours"):
            return httpx.Response(200, json={"results": [hour_item(NOW - timedelta(hours=h)) for h in range(hours)]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------- parsing ----------
def test_parse_basic_and_period_end_is_observed_time():
    r = parse_hour_item(hour_item(NOW), "pm25", "\u00b5g/m\u00b3", NOW)
    assert r == {"observed_at": NOW, "parameter": "pm25", "value": 50.0, "unit": "\u00b5g/m\u00b3"}


@pytest.mark.parametrize("item", [
    {**hour_item(NOW), "value": None},                      # missing value
    hour_item(NOW, coverage=60),                            # below 75% hourly coverage
    hour_item(NOW, value=-5),                               # impossible negative
    hour_item(NOW + timedelta(days=3)),                     # future timestamp
    {"value": 5, "period": {}},                             # no timestamp
])
def test_parse_rejects_bad_rows(item):
    assert parse_hour_item(item, "pm25", "x", NOW) is None


def test_parse_unwanted_parameter_and_nonnumeric():
    assert parse_hour_item(hour_item(NOW), "nox", "ppb", NOW) is None
    assert parse_hour_item({**hour_item(NOW), "value": "abc"}, "pm25", "x", NOW) is None


# ---------- collection ----------
def test_collect_stores_only_wanted_parameters_and_is_idempotent(db):
    n1 = collect_openaq(db, "bhubaneswar", client=make_client(), sleep=lambda s: None, now=NOW, api_key="k")
    assert n1 == 2 * 10 * 3                                         # 2 stations x 10 wanted sensors x 3 hours
    assert db.scalar(select(func.count(Location.id))) == 2
    params = {p for (p,) in db.execute(select(PollutionObservation.parameter).distinct())}
    assert params == {n for n, _ in PARAMS} - {"no", "nox"}
    assert all(o.data_origin == "OBSERVED" and o.source == "openaq" for o in db.scalars(select(PollutionObservation)))
    n2 = collect_openaq(db, "bhubaneswar", client=make_client(), sleep=lambda s: None, now=NOW, api_key="k")
    assert n2 == 0 and db.scalar(select(func.count(PollutionObservation.id))) == n1


def test_second_run_only_requests_since_last_value(db):
    collect_openaq(db, "bhubaneswar", client=make_client(), sleep=lambda s: None, now=NOW, api_key="k")
    rec = []
    collect_openaq(db, "bhubaneswar", client=make_client(record=rec), sleep=lambda s: None, now=NOW, api_key="k")
    sensor_calls = [r for r in rec if "/sensors/" in r.url.path]
    frm = datetime.strptime(sensor_calls[0].url.params["datetime_from"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert frm >= NOW - timedelta(hours=3, minutes=1)               # last stored hour minus 3 h overlap, not 48 h


def test_revised_value_is_updated(db):
    collect_openaq(db, "bhubaneswar", client=make_client(hours=1), sleep=lambda s: None, now=NOW, api_key="k")

    def handler(req):
        if req.url.path.startswith("/v3/locations/"):
            return httpx.Response(200, json={"results": [location_json(int(req.url.path.rsplit("/", 1)[1]))]})
        return httpx.Response(200, json={"results": [hour_item(NOW, value=55.0)]})
    n = collect_openaq(db, "bhubaneswar", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, now=NOW, api_key="k")
    assert n == 20 and db.scalar(select(func.max(PollutionObservation.value))) == 55.0


def test_missing_key_is_a_clear_error_and_recorded(db, monkeypatch):
    monkeypatch.setattr(openaq.get_settings(), "openaq_api_key", "")
    with pytest.raises(RuntimeError, match="OPENAQ_API_KEY"):
        collect_openaq(db, "bhubaneswar", client=make_client(), sleep=lambda s: None, now=NOW)
    res = ingestion.run_collector(db, "air-quality")
    st = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == "openaq"))
    assert res["ok"] is False and "OPENAQ_API_KEY" in st.last_error and st.consecutive_failures == 1


def test_one_failing_station_does_not_hide_the_other(db):
    def handler(req):
        p = req.url.path
        if p.endswith("/3409505"):
            return httpx.Response(404, text="nope")
        if p.startswith("/v3/locations/"):
            return httpx.Response(200, json={"results": [location_json(int(p.rsplit("/", 1)[1]))]})
        return httpx.Response(200, json={"results": [hour_item(NOW)]})
    n = collect_openaq(db, "bhubaneswar", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, now=NOW, api_key="k")
    assert n == 10
    def all_fail(req):
        return httpx.Response(404)
    with pytest.raises(RuntimeError, match="station"):
        collect_openaq(db, "bhubaneswar", client=httpx.Client(transport=httpx.MockTransport(all_fail)), sleep=lambda s: None, now=NOW, api_key="k")


def test_cuttack_excluded_by_default_included_on_request(db):
    collect_openaq(db, "bhubaneswar", client=make_client(hours=1), sleep=lambda s: None, now=NOW, api_key="k")
    assert {l.external_id for l in db.scalars(select(Location))} == {"3409505", "3409508"}
    collect_openaq(db, "bhubaneswar", client=make_client(hours=1), sleep=lambda s: None, now=NOW, api_key="k", include_cuttack=True)
    assert "3409506" in {l.external_id for l in db.scalars(select(Location))}


def test_backfill_chunks_and_resumes(db):
    msgs, rec = [], []
    n = backfill_openaq(db, "bhubaneswar", days=65, client=make_client(hours=2, record=rec), sleep=lambda s: None, now=NOW,
                        api_key="k", progress=msgs.append)
    chunks = [r for r in rec if "/sensors/" in r.url.path]
    assert len(chunks) == 2 * 10 * 3                                # 65 days in 30-day chunks = 3 per sensor
    assert n > 0 and any("pm25" in m for m in msgs)
    again = backfill_openaq(db, "bhubaneswar", days=65, client=make_client(hours=2), sleep=lambda s: None, now=NOW, api_key="k", progress=lambda m: None)
    assert again == 0                                               # nothing new on re-run
