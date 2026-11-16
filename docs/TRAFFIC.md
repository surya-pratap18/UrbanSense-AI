# Traffic Module (Phase 4A: collection, APIs, hotspot ranking)

## What TomTom gives us (verified with a real response for Bhubaneswar)
`flowSegmentData`: currentSpeed, freeFlowSpeed (km/h), travel times, confidence (0-1), roadClosure, `frc` (functional road class) and the segment geometry.
- A segment is TomTom's own road piece (the test returned about 5 km at zoom 10). Different query points can return the SAME segment, so we de-duplicate.
- **No measurement timestamp** is returned. `observed_at` = the minute we received the answer.
- `congestion_ratio = currentSpeed / freeFlowSpeed`. Levels (this project's thresholds): >= 0.8 free_flow, >= 0.6 moderate, >= 0.4 heavy, below severe, plus `closed`.

## Quota design (free tier: 2,500 requests/day)
About 20 segments x 96 runs/day = 1,920 requests. The collector refuses to run if the last 24 h plus this run would exceed `TOMTOM_DAILY_BUDGET` (default 2,200), and stops immediately on a 401/403/429 instead of retrying 20 times.

## Setup (once)
```
cd backend
python -m scripts.discover_segments --probe             # 9 requests: compares zoom 10/12/14, saves nothing
python -m scripts.discover_segments --zoom 12 --dry-run # preview ~20 segments (about 80 requests), saves nothing
python -m scripts.discover_segments --zoom 12           # save them
python -m scripts.run_collector traffic                 # first real collection
```
Candidates come from OpenStreetMap (named trunk/primary/secondary roads in a Bhubaneswar bounding box) via the Overpass API.
Overpass is a free shared server that is often busy (502/504): the code tries two backup servers and caches the road list in `datasets/external/overpass_roads.json`, so only the first run needs it (`--refresh-roads` downloads again). A failure here happens before any TomTom request, so it costs no quota. Pick the zoom whose segments are roughly 0.3-3 km long.
Schedule: `.github/workflows/traffic.yml` runs every 15 minutes (public repo recommended: unlimited free minutes). Add GitHub secret `TOMTOM_API_KEY`.

## Choosing segments (what we learned from the real Bhubaneswar run)
- Zoom 10, 12 and 14 returned identical segments: TomTom decides segmentation, so keep zoom 12. Segment length varies by road (0.1 km to 6.5 km).
- Defaults now keep segments of 300 m to 6 km and ignore generic OSM names such as "Service Road".
- A segment's name is the OpenStreetMap road at the point that first hit it (one segment can carry the name of a neighbouring road); treat names as a guide.
- A segment's speed is an average over its whole length: a short local jam on a long segment is diluted. State this limitation in the report.
- Switch segments on/off without new TomTom requests: `python -m scripts.manage_segments list|off ID...|on ID...` (or `PATCH /api/admin/segments/{id}`).

## Endpoints
`GET /api/traffic/segments` (geometry for the map), `/current`, `/history?segment_id=`, `/hotspots?days=7`.
Hotspots are a transparent ranking, not clustering: score = 0.5*(1 - mean ratio) + 0.5*share of readings below 0.6. `reliable` needs >= 24 readings.

## Forecasting (Phase 4B, after data exists)
No Bhubaneswar history exists until collection starts. Plan: collect at least 2-4 weeks, then train XGBoost on the congestion ratio (+15/+30/+60 min) with persistence and time-of-day baselines, exactly as for air quality. PEMS-BAY/METR-LA (US data) are used only as a separate benchmark, never as Bhubaneswar ground truth.
