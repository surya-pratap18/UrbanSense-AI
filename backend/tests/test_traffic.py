import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.collectors.overpass import build_candidates
from app.collectors.tomtom import collect_tomtom, parse_flow
from app.core.config import get_settings
from app.models import DataSourceStatus, RoadSegment, TrafficObservation
from app.services import ingestion
from app.services.segment_discovery import discover
from app.services.traffic import congestion_level, hotspot_ranking, polyline_length_m, thin

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def flow(cs=20, ff=40, frc="FRC3", closed=False, conf=1, base=(20.30, 85.80), n=5):
    coords = [{"latitude": base[0] + i * 0.002, "longitude": base[1]} for i in range(n)]
    return {"flowSegmentData": {"frc": frc, "currentSpeed": cs, "freeFlowSpeed": ff, "currentTravelTime": 100, "freeFlowTravelTime": 50,
                                "confidence": conf, "roadClosure": closed, "coordinates": {"coordinate": coords}}}


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def add_segments(db, n=3):
    segs = []
    for i in range(n):
        feat = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[85.8, 20.3], [85.8, 20.31]]},
                "properties": {"frc": "FRC3", "frc_label": "secondary road", "length_m": 900, "zoom": 12, "fingerprint": f"fp{i}"}}
        s = RoadSegment(city_id=1, name=f"Road {i}", road_type="primary", latitude=20.30 + i * 0.01, longitude=85.80,
                        geometry_geojson=json.dumps(feat), is_active=True)
        db.add(s)
        segs.append(s)
    db.commit()
    return segs


# ---------- pure functions ----------
def test_parse_flow_matches_real_tomtom_shape():
    r = parse_flow(flow(28, 28)["flowSegmentData"])
    assert r["congestion_ratio"] == 1.0 and r["road_closure"] is False and r["confidence"] == 1.0 and r["frc"] == "FRC3"
    assert parse_flow(flow(10, 40)["flowSegmentData"])["congestion_ratio"] == 0.25


@pytest.mark.parametrize("d", [{"currentSpeed": 20, "freeFlowSpeed": 0}, {"currentSpeed": -1, "freeFlowSpeed": 30},
                               {"currentSpeed": "x", "freeFlowSpeed": 30}, {"freeFlowSpeed": 30}, {"currentSpeed": 900, "freeFlowSpeed": 30}])
def test_parse_flow_rejects_unusable(d):
    assert parse_flow(d) is None


def test_congestion_levels():
    assert [congestion_level(r) for r in (1.2, 0.8, 0.79, 0.6, 0.59, 0.4, 0.39, 0.0)] == \
        ["free_flow", "free_flow", "moderate", "moderate", "heavy", "heavy", "severe", "severe"]
    assert congestion_level(0.9, closed=True) == "closed" and congestion_level(None) is None


def test_geometry_helpers():
    assert polyline_length_m([(20.0, 85.0), (20.01, 85.0)]) == pytest.approx(1112, abs=5)
    pts = [(20 + i * 1e-4, 85.0) for i in range(500)]
    t = thin(pts, 60)
    assert len(t) <= 61 and t[0] == pts[0] and t[-1] == pts[-1]


# ---------- collector ----------
def test_collect_stores_one_row_per_segment_and_is_idempotent(db):
    add_segments(db, 3)
    calls = []

    def h(req):
        calls.append(req)
        assert "key" in req.url.params and "," in req.url.params["point"]
        return httpx.Response(200, json=flow(15, 30))
    assert collect_tomtom(db, "bhubaneswar", client=client_for(h), sleep=lambda s: None, now=NOW, api_key="k") == 3
    assert collect_tomtom(db, "bhubaneswar", client=client_for(h), sleep=lambda s: None, now=NOW, api_key="k") == 0   # same minute: no duplicates
    assert db.scalar(select(func.count(TrafficObservation.id))) == 3
    o = db.scalar(select(TrafficObservation))
    assert o.congestion_ratio == 0.5 and o.source == "tomtom_flow" and o.data_origin == "OBSERVED"
    assert "/absolute/12/" in str(calls[0].url)                                  # zoom comes from the segment's stored properties


def test_fatal_error_stops_immediately_to_save_quota(db):
    add_segments(db, 5)
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(403, text="Forbidden")
    with pytest.raises(RuntimeError, match="Stopping to protect your quota"):
        collect_tomtom(db, "bhubaneswar", client=client_for(h), sleep=lambda s: None, now=NOW, api_key="k")
    assert len(calls) == 1


def test_partial_failure_keeps_good_segments(db):
    add_segments(db, 3)
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(404, text="x") if n["i"] == 2 else httpx.Response(200, json=flow())
    assert collect_tomtom(db, "bhubaneswar", client=client_for(h), sleep=lambda s: None, now=NOW, api_key="k") == 2


def test_budget_guard_blocks_before_any_request(db, monkeypatch):
    add_segments(db, 3)
    monkeypatch.setattr(get_settings(), "tomtom_daily_budget", 5)
    ok_client = client_for(lambda r: httpx.Response(200, json=flow()))
    collect_tomtom(db, "bhubaneswar", client=ok_client, sleep=lambda s: None, now=NOW, api_key="k")
    calls = []
    with pytest.raises(RuntimeError, match="budget guard"):
        collect_tomtom(db, "bhubaneswar", client=client_for(lambda r: calls.append(1) or httpx.Response(200, json=flow())),
                       sleep=lambda s: None, now=NOW + timedelta(minutes=15), api_key="k")
    assert calls == []


def test_missing_key_no_segments_and_status_recording(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "tomtom_api_key", "")
    with pytest.raises(RuntimeError, match="TOMTOM_API_KEY"):
        collect_tomtom(db, "bhubaneswar", sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="No road segments"):
        collect_tomtom(db, "bhubaneswar", sleep=lambda s: None, api_key="k")
    res = ingestion.run_collector(db, "traffic")
    st = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == "tomtom_traffic"))
    assert res["ok"] is False and st.consecutive_failures == 1


# ---------- discovery ----------
ROADS = [{"id": 1, "tags": {"name": "Road X", "highway": "primary"}, "center": {"lat": 20.301, "lon": 85.80}},
         {"id": 2, "tags": {"name": "Road Y", "highway": "trunk"}, "center": {"lat": 20.302, "lon": 85.80}},   # same TomTom segment as X
         {"id": 3, "tags": {"name": "Road Z", "highway": "secondary"}, "center": {"lat": 20.350, "lon": 85.85}},
         {"id": 4, "tags": {"highway": "primary"}, "center": {"lat": 20.31, "lon": 85.81}},                      # unnamed: ignored
         {"id": 5, "tags": {"name": "Footpath", "highway": "footway"}, "center": {"lat": 20.32, "lon": 85.82}}]  # wrong class: ignored


def discovery_handler(req):
    lat = float(req.url.params["point"].split(",")[0])
    return httpx.Response(200, json=flow(base=(round(lat, 2), 85.8), n=4))     # points with equal round(lat,2) -> identical segment


def test_candidates_filter_and_rank():
    c = build_candidates(ROADS, 10)
    assert [x["name"] for x in c] == ["Road Y", "Road X", "Road Z"]            # trunk first, unnamed/footway dropped


def test_discover_dedupes_segments_and_saves_geometry(db):
    r = discover(db, "bhubaneswar", "k", zoom=12, roads=ROADS, client=client_for(discovery_handler), sleep=lambda s: None, progress=lambda m: None)
    assert r["candidates"] == 3 and r["unique_segments"] == 2 and r["saved"] == 2
    segs = db.scalars(select(RoadSegment)).all()
    assert len(segs) == 2 and all(s.is_active for s in segs)
    props = json.loads(segs[0].geometry_geojson)["properties"]
    assert props["zoom"] == 12 and props["fingerprint"] and props["length_m"] > 100
    again = discover(db, "bhubaneswar", "k", zoom=12, roads=ROADS, client=client_for(discovery_handler), sleep=lambda s: None, progress=lambda m: None)
    assert again["saved"] == 0 and db.scalar(select(func.count(RoadSegment.id))) == 2        # re-run adds nothing


def test_discover_dry_run_saves_nothing_and_filters_long_segments(db):
    r = discover(db, "bhubaneswar", "k", zoom=12, roads=ROADS, client=client_for(discovery_handler), sleep=lambda s: None,
                 dry_run=True, max_length_m=100, progress=lambda m: None)
    assert r["saved"] == 0 and r["selected"] == 0 and db.scalar(select(func.count(RoadSegment.id))) == 0


# ---------- API ----------
def seed_obs(db, seg, ratios, end=None, step=15):
    end = end or NOW
    for i, r in enumerate(reversed(ratios)):
        db.add(TrafficObservation(segment_id=seg.id, observed_at=end - timedelta(minutes=step * i), current_speed_kmh=r * 40,
                                  free_flow_speed_kmh=40.0, congestion_ratio=r, source="tomtom_flow", data_origin="OBSERVED"))
    db.commit()


def test_empty_api_is_honest(client):
    assert client.get("/api/traffic/current").json()["data"] == []
    assert client.get("/api/traffic/segments").json()["data"] == []
    assert client.get("/api/traffic/history?segment_id=1").status_code == 404
    assert client.get("/api/traffic/hotspots").json()["data"] == []


def test_current_states_levels_and_segments(client, db):
    a, b = add_segments(db, 2)
    seed_obs(db, a, [0.9, 0.5])                                           # fresh, heavy congestion now
    seed_obs(db, b, [0.9], end=NOW - timedelta(hours=5))                  # stale
    cur = {x["name"]: x for x in client.get("/api/traffic/current").json()["data"]}
    assert cur["Road 0"]["data_state"] == "LIVE" and cur["Road 0"]["latest"]["congestion_level"] == "heavy"
    assert cur["Road 1"]["data_state"] == "HISTORICAL"                    # old data is never LIVE
    seg = client.get("/api/traffic/segments").json()
    assert seg["data"][0]["geometry"]["type"] == "LineString" and "TomTom" in seg["meta"]["attribution"]
    st = {r["source_key"]: r for r in client.get("/api/dashboard/data-status").json()["data"]}
    assert st["tomtom_traffic"]["state"] == "LIVE"


def test_history_pagination_and_validation(client, db):
    a, = add_segments(db, 1)
    seed_obs(db, a, [0.9] * 20)
    r = client.get(f"/api/traffic/history?segment_id={a.id}&page=1&page_size=8").json()
    assert len(r["data"]) == 8 and r["meta"]["total"] == 20
    t = [x["observed_at"] for x in r["data"]]
    assert t == sorted(t)
    assert client.get(f"/api/traffic/history?segment_id={a.id}&start=2026-01-02T00:00:00Z&end=2026-01-01T00:00:00Z").status_code == 422


def test_hotspot_ranking_prefers_recurrent_congestion_and_flags_thin_data(client, db):
    a, b, c = add_segments(db, 3)
    seed_obs(db, a, [0.5] * 18 + [0.95] * 12)                             # congested 60% of the time
    seed_obs(db, b, [0.95] * 30)                                          # always free
    seed_obs(db, c, [0.3] * 3)                                            # very bad but only 3 readings
    rows = client.get("/api/traffic/hotspots?days=7").json()["data"]
    by = {r["name"]: r for r in rows}
    assert rows[0]["name"] != "Road 1" and by["Road 0"]["score"] > by["Road 1"]["score"]
    assert by["Road 0"]["reliable"] is True and by["Road 2"]["reliable"] is False
    assert "readings" in by["Road 0"]["explanation"]
    assert hotspot_ranking(db, days=7, limit=1)[0]["score"] == rows[0]["score"]


def test_traffic_ingest_endpoint_uses_collector(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "s")
    monkeypatch.setitem(ingestion.COLLECTORS, "traffic", ("tomtom_traffic", lambda d: 7))
    assert client.post("/api/ingest/traffic", headers={"X-Cron-Secret": "s"}).json()["data"]["records"] == 7


def test_discover_ignores_generic_names_before_spending_quota(db):
    roads = ROADS + [{"id": 9, "tags": {"name": "Service Road", "highway": "primary"}, "center": {"lat": 20.40, "lon": 85.90}}]
    calls = []

    def h(req):
        calls.append(1)
        return discovery_handler(req)
    r = discover(db, "bhubaneswar", "k", zoom=12, roads=roads, client=client_for(h), sleep=lambda s: None, progress=lambda m: None)
    assert r["candidates"] == 3 and len(calls) == 3                      # 'Service Road' never queried
    assert all("Service" not in s.name for s in db.scalars(select(RoadSegment)))


def test_discover_drops_too_short_and_too_long_segments(db):
    def h(req):
        lat = float(req.url.params["point"].split(",")[0])
        n = 2 if lat < 20.31 else 40                                       # ~220 m vs ~8.7 km
        return httpx.Response(200, json=flow(base=(round(lat, 2), 85.8), n=n))
    r = discover(db, "bhubaneswar", "k", zoom=12, roads=ROADS, client=client_for(h), sleep=lambda s: None, progress=lambda m: None)
    assert r["unique_segments"] == 2 and r["selected"] == 0


def test_admin_can_switch_segments_off(client, db):
    a, b = add_segments(db, 2)
    tok = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpass1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.patch(f"/api/admin/segments/{a.id}", json={"is_active": False}).status_code == 401
    assert client.patch(f"/api/admin/segments/{a.id}", json={"is_active": False}, headers=h).json()["data"]["is_active"] is False
    assert client.patch("/api/admin/segments/999", json={"is_active": False}, headers=h).status_code == 404
    assert [s["name"] for s in client.get("/api/traffic/segments").json()["data"]] == ["Road 1"]       # off = hidden from the map
    assert len(client.get("/api/admin/segments", headers=h).json()["data"]) == 2                       # admin still sees it
    calls = []
    collect_tomtom(db, "bhubaneswar", client=client_for(lambda r: calls.append(1) or httpx.Response(200, json=flow())), sleep=lambda s: None, now=NOW, api_key="k")
    assert len(calls) == 1                                                                              # off segment costs no quota


# ---------- Overpass robustness ----------
from app.collectors.http import FetchError  # noqa: E402
from app.collectors.overpass import ENDPOINTS, fetch_roads  # noqa: E402


def overpass_client(per_host: dict, calls: list):
    def h(req):
        host = req.url.host
        calls.append(host)
        status, body = per_host[host]
        return httpx.Response(status, json=body) if status == 200 else httpx.Response(status, text="busy")
    return client_for(h)


def test_overpass_fails_over_to_mirror_and_caches(tmp_path):
    hosts = [httpx.URL(u).host for u in ENDPOINTS]
    calls = []
    c = overpass_client({hosts[0]: (504, {}), hosts[1]: (200, {"elements": ROADS}), hosts[2]: (200, {"elements": []})}, calls)
    cache = tmp_path / "roads.json"
    assert fetch_roads(client=c, sleep=lambda s: None, cache_path=cache) == ROADS
    assert hosts[1] in calls and hosts[2] not in calls and cache.exists()
    calls.clear()
    assert fetch_roads(client=c, sleep=lambda s: None, cache_path=cache) == ROADS     # second call: served from cache
    assert calls == []
    assert fetch_roads(client=c, sleep=lambda s: None, cache_path=cache, refresh=True) == ROADS
    assert calls                                                                         # refresh forces a download


def test_overpass_all_servers_down_gives_a_helpful_error(tmp_path):
    hosts = [httpx.URL(u).host for u in ENDPOINTS]
    c = overpass_client({h: (502, {}) for h in hosts}, [])
    with pytest.raises(FetchError, match="Wait a few minutes"):
        fetch_roads(client=c, sleep=lambda s: None, cache_path=tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()                                            # failures are never cached


def test_cache_ignored_when_area_changes(tmp_path):
    hosts = [httpx.URL(u).host for u in ENDPOINTS]
    calls = []
    c = overpass_client({hosts[0]: (200, {"elements": ROADS})} | {h: (200, {"elements": ROADS}) for h in hosts[1:]}, calls)
    fetch_roads(client=c, sleep=lambda s: None, cache_path=tmp_path / "r.json")
    calls.clear()
    fetch_roads(bbox=(20.0, 85.0, 20.1, 85.1), client=c, sleep=lambda s: None, cache_path=tmp_path / "r.json")
    assert calls                                                                         # different bbox -> not served from old cache
