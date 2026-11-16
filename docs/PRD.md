# UrbanSense AI: Product Requirements (v0.1)
**Goal:** a free-to-run smart-city intelligence platform for Bhubaneswar covering traffic, air quality, waste, hotspots and resource planning.
**Users:** `user` (view dashboards, history, reports) and `admin` (users, data sources, models, retraining).
**Non-goals:** official government alerts, guaranteed forecast accuracy, paid services.
**Honesty rules:** every value carries a data state (LIVE/DELAYED/HISTORICAL/SIMULATED/UNAVAILABLE) and origin (OBSERVED/SIMULATED/BENCHMARK). Missing sensor values are never zero. Metrics shown are computed only from held-out test data.
**Modules:** (1) Traffic congestion ratio forecast 15/30/60 min. (2) Air quality PM2.5/PM10 forecast 1/3/6 h with CPCB-style indicative index. (3) Waste: forecast, capacity gap, priority (simulated until real data imported). (4) Hotspots + OR-Tools resource allocation with explanations. Weather supports (1) and (2).
**Build phases:** 1 Foundation (done) -> 2 Weather + ingestion framework -> 3 Air quality -> 4 Traffic -> 5 Waste -> 6 Hotspots + optimization -> 7 Frontend -> 8 Deployment, report, slides.
