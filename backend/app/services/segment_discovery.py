"""One-off selection of the road segments to monitor (costs ~1 TomTom request per candidate; hard cap 150)."""
import json
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.overpass import HW_RANK, build_candidates, fetch_roads
from app.collectors.tomtom import fetch_flow, is_fatal
from app.models import City, RoadSegment
from app.services.traffic import FRC_LABEL, polyline_length_m, segment_props, thin


def fingerprint(coords: list[tuple[float, float]]) -> str:
    a, b = coords[0], coords[-1]
    return f"{a[0]:.4f},{a[1]:.4f}>{b[0]:.4f},{b[1]:.4f}"


def describe_flow(flow: dict) -> dict | None:
    pts = [(p["latitude"], p["longitude"]) for p in (flow.get("coordinates") or {}).get("coordinate", [])]
    if len(pts) < 2:
        return None
    return {"coords": pts, "length_m": polyline_length_m(pts), "frc": flow.get("frc"), "fingerprint": fingerprint(pts),
            "free_flow_kmh": flow.get("freeFlowSpeed"), "current_kmh": flow.get("currentSpeed")}


def discover(db: Session, city_slug: str, key: str, *, zoom: int, client=None, sleep=time.sleep, max_candidates: int = 80,
             keep: int = 20, min_length_m: float = 300, max_length_m: float = 6000, per_road: int = 2, roads: list | None = None, refresh_roads: bool = False,
             exclude_names: tuple[str, ...] = ("service road",),
             dry_run: bool = False, throttle: float = 0.3, progress=print) -> dict:
    max_candidates = min(max_candidates, 150)
    city = db.scalar(select(City).where(City.slug == city_slug))
    if city is None:
        raise RuntimeError("City not found: run scripts.seed first")
    roads = roads if roads is not None else fetch_roads(client=client, sleep=sleep, refresh=refresh_roads)
    banned = {n.lower() for n in exclude_names}      # generic OSM names (e.g. 'Service Road') cannot be traced to one road
    roads = [e for e in roads if (e.get("tags") or {}).get("name", "").strip().lower() not in banned]
    cands = build_candidates(roads, max_candidates)
    progress(f"{len(cands)} candidate road points from OpenStreetMap; querying TomTom (zoom {zoom}) ...")
    seen, found = set(), []
    for c in cands:
        sleep(throttle)
        try:
            info = describe_flow(fetch_flow(c["lat"], c["lon"], key, zoom, client=client, sleep=sleep))
        except Exception as e:  # noqa: BLE001
            if is_fatal(e):
                raise RuntimeError(f"TomTom refused the request ({e}). Check TOMTOM_API_KEY / quota.") from e
            progress(f"  skip {c['name']}: {e}")
            continue
        if info is None or info["fingerprint"] in seen:
            continue
        seen.add(info["fingerprint"])
        found.append({**c, **info})
    ok = [f for f in found if min_length_m <= f["length_m"] <= max_length_m]
    ok.sort(key=lambda f: (str(f["frc"]), HW_RANK[f["highway"]], f["name"]))
    chosen, per = [], {}
    for f in ok:
        if per.get(f["name"], 0) < per_road and len(chosen) < keep:
            chosen.append(f)
            per[f["name"]] = per.get(f["name"], 0) + 1
    existing = {segment_props(s).get("fingerprint") for s in db.scalars(select(RoadSegment).where(RoadSegment.city_id == city.id))}
    saved, idx = 0, {}
    for f in chosen:
        idx[f["name"]] = idx.get(f["name"], 0) + 1
        label = FRC_LABEL.get(f["frc"], "road")
        progress(f"  {f['name']:32s} {f['highway']:9s} {str(f['frc']):5s} {f['length_m'] / 1000:5.2f} km  free-flow {f['free_flow_kmh']} km/h")
        if dry_run or f["fingerprint"] in existing:
            continue
        feature = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[lo, la] for la, lo in thin(f["coords"])]},
                   "properties": {"frc": f["frc"], "frc_label": label, "length_m": round(f["length_m"]), "zoom": zoom,
                                  "fingerprint": f["fingerprint"], "osm_name": f["name"], "source": "tomtom_flowSegmentData + OpenStreetMap"}}
        db.add(RoadSegment(city_id=city.id, name=f"{f['name']} ({idx[f['name']]})", road_type=f["highway"], latitude=f["lat"], longitude=f["lon"],
                           osm_way_id=f["osm_id"], geometry_geojson=json.dumps(feature), is_active=True))
        saved += 1
    db.commit()
    return {"candidates": len(cands), "unique_segments": len(found), "selected": len(chosen), "saved": saved, "dry_run": dry_run}
