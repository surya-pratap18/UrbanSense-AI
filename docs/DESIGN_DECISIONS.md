# Design Decisions (changes from the original spec, and why)

| Spec item | Problem | Decision |
|---|---|---|
| APScheduler as the collector | Free Render sleeps after 15 min idle | GitHub Actions cron runs the collectors; APScheduler only for local dev |
| TomTom polling | 2,500 requests/day free | ~20 chosen road points, every 15 min; refresh endpoint cached + cooldown |
| PEMS-BAY/METR-LA for Bhubaneswar | US data, different road behaviour; no rain/road-type columns | Benchmark only. Local model predicts congestion ratio from collected data. UI shows calibration status. No LSTM |
| "Official AQI" hourly | CPCB AQI needs 24h/8h averages and min-data rules | "CPCB-style indicative index", labelled as such |
| Ward waste data | Not publicly available | SIMULATED scenario mode + CSV import; no accuracy claimed in simulated mode; predictions carry `trained_on` flag |
| DBSCAN everywhere | Too few points for traffic/pollution | Ranking + recurrence for traffic/pollution; DBSCAN (haversine) for waste zones and accumulated events |
| Heavy libs on 512 MB host | OSMnx/GeoPandas/OR-Tools memory | OSMnx/GeoPandas offline -> GeoJSON; training offline; backend loads small .joblib files |
| Big benchmark datasets in Postgres | Supabase free DB ~500 MB | Benchmarks stay as Parquet offline; Postgres holds only live Bhubaneswar data + retention job |
| Supabase Auth + custom auth | Redundant | One system: custom JWT (bcrypt), roles `user` / `admin`; admins created only by seed script |
| Retrain endpoint trains in-process | Too heavy for free host | Endpoint triggers a GitHub Actions workflow |

Access policy: city data endpoints are public read (demo-friendly); admin, retrain and ingestion endpoints require admin JWT or `CRON_SECRET`.
