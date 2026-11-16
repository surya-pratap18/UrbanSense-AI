# Architecture
```
 GitHub Actions cron (free) --HTTP/CLI--> collectors --> Supabase PostgreSQL <-- FastAPI (Render free) <-- React (Cloudflare Pages)
        (TomTom 15m, OpenAQ 30m, Open-Meteo 60m)                                   |
 Offline (laptop/Colab): OSMnx/GeoPandas -> GeoJSON; training scripts -> small .joblib in ml_engine/saved_models
```
- Collectors share one pipeline: fetch (timeout + retry/backoff) -> validate -> dedupe (unique constraints) -> store -> update `data_source_status`.
- Backend serves only light inference (XGBoost/RandomForest .joblib). No training in the API.
- Cold start (~1 min): frontend shows a "waking server" state; `/api/health` is cheap for pings.
- Timestamps stored UTC; displayed Asia/Kolkata.
