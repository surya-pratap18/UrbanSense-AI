# Data Ingestion Guide

## How it works
Every collector follows the same pipeline: fetch (15 s timeout, 3 attempts, exponential backoff + jitter, honours `Retry-After`) -> validate (bad timestamps skipped, impossible values become NULL, never 0) -> upsert (unique constraints = no duplicates) -> update `data_source_status` (attempt time, last success, error text, consecutive failures, records).
A failed run never erases the previous `last_success_at`, so the dashboard keeps telling the truth about data age.

## Run a collector by hand (local)
```
cd backend
python -m scripts.run_collector weather
```
Prints `{'ok': True, 'source': 'open_meteo', 'records': N}`. Exit code 1 on failure.
Then open `/docs` and call `GET /api/weather/current`: `data_state` should be `LIVE`.

Collectors available: `weather`, `air-quality` (traffic arrives in Phase 4). The workflow also needs a GitHub secret `OPENAQ_API_KEY`.

## Trigger over HTTP
`POST /api/ingest/weather`: allowed for (a) an admin JWT (5-minute cooldown, protects free quotas) or (b) header `X-Cron-Secret: <CRON_SECRET>` (no cooldown).

## Schedule it for free (GitHub Actions)
1. Push the project to a **public** GitHub repo (public repos get unlimited free Actions minutes). Make sure `.env` is NOT committed.
2. Point `DATABASE_URL` in your local `.env` at Supabase and run `python -m scripts.seed` once. This creates the tables there and your admin user.
3. GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret: `DATABASE_URL` (the Supabase **Session pooler** string).
4. Actions tab -> "Scheduled data ingestion" -> **Run workflow** to test. It then runs hourly by itself (GitHub may delay it a few minutes; the app labels data DELAYED if it is late).
Note: GitHub pauses scheduled workflows in repos with no activity for 60 days; re-enable them from the Actions tab.

## Data-quality notes
- Open-Meteo values are model-based grid-cell estimates, not weather-station readings. The API says so in `meta.note`.
- Hourly rows in the past are stored as observed (`is_forecast=false`); future rows as forecasts and are refreshed each run.
