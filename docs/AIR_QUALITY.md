# Air Quality Module (Phase 3A: data + API; Phase 3B: forecasting models)

## Stations (verified from OpenAQ, Nov 2026)
| Station | OpenAQ id | Used |
|---|---|---|
| Lingraj Mandir, Bhubaneswar (OSPCB) | 3409505 | yes |
| Patia, Bhubaneswar (OSPCB) | 3409508 | yes |
| CDA Area, Cuttack (OSPCB) | 3409506 | no (different city). Enable with `OPENAQ_INCLUDE_CUTTACK=true` |
Provider: CPCB / OSPCB, history from Feb 2025. Each station reports PM2.5, PM10, NO2, SO2, CO, O3 and its own temperature, humidity, wind speed and direction.

## Data rules
- Hourly averages from `/v3/sensors/{id}/hours`. `observed_at` = END of the hour (a value is only known after the hour; prevents leakage in forecasting).
- Skipped (treated as missing, never 0): coverage < 75 %, negative or impossible values, invalid or future timestamps.
- Stored with original units (gases are ppb in OpenAQ). Conversion to ug/m3 happens only when computing the index (25 C, 1 atm: approximate).
- Stations are never merged; every row keeps its `location_id`.

## CPCB-style indicative index
24 h mean for PM2.5/PM10/NO2/SO2 (>= 16 of 24 hours), max 8 h mean for O3/CO (>= 6 of 8 hours), overall = highest sub-index, valid only with >= 3 pollutants incl. PM2.5 or PM10. The API always sets `official: false`. PM2.5 and PM10 breakpoints were checked against CPCB tables; before the final report, re-check the NO2/SO2/O3/CO upper bands against the official CPCB PDF.

## Commands (run in `backend/`)
```
python -m scripts.probe_openaq            # shows what OpenAQ returns (never prints your key)
python -m scripts.backfill_openaq --days 400   # one-off history, ~6 min, safe to re-run
python -m scripts.run_collector air-quality    # regular hourly update
```
## Endpoints
`GET /api/pollution/stations`, `GET /api/pollution/current[?station_id=]`, `GET /api/pollution/history?station_id=&parameter=pm25&start=&end=&page=&page_size=`.
Size estimate: 400 days x 2 stations x 10 parameters is about 190,000 rows (roughly 40-60 MB), fine for Supabase free (500 MB).
