# ML Documentation

## Air-quality forecasting (PM2.5 and PM10, +1 h / +3 h / +6 h)
**Data:** hourly CPCB/OSPCB station averages via OpenAQ (Lingraj Mandir, Patia) + Open-Meteo weather (rainfall, cloud).
**Features (all known at time t):** lags of PM2.5/PM10 (0-24 h), rolling means, NO2/SO2/CO/O3 now and lagged, the station's own temperature/humidity/wind, rainfall (now, 6 h and 24 h sums), cloud cover, hour/weekday/month (local time), station code. A unit test corrupts all data after time t and checks that features at t do not change (no look-ahead). Missing values stay missing: XGBoost handles NaN natively, Random Forest uses a median imputer on FEATURES only; missing TARGETS are dropped, never filled.
**Split:** chronological 70/15/15 with a 6-hour embargo between parts. **Baselines:** persistence and hour-of-day mean (from training data only).
**Candidates:** XGBoost (depth 4 and 6, early stopping) and Random Forest; winner = lowest validation RMSE. The deployed model is the one evaluated on test (trained on the train part only).
**Metrics:** MAE, RMSE, R2, MAPE (only on targets >= 10 ug/m3), all on the held-out test period, identical rows for model and baselines. **Interval:** 80 % split-conformal interval (constant width), coverage re-measured on test.
**Honesty flags:** `LOCALLY_VALIDATED` = beat both baselines on test RMSE; `NO_SKILL_OVER_BASELINE` = did not. +1 h forecasts are often hard to beat with persistence; report whatever the data shows.
**Limits:** two stations, about 13 months of history; the test period is one season (post-monsoon/winter), so results may not transfer to monsoon months. Weather features in training come from the ERA5 archive while live features come from the forecast API (slightly different sources). Retrain periodically; retrain whenever xgboost/scikit-learn versions change (pickled models are version-sensitive).

## Where to run training
Training/forecasting need pandas + xgboost + scikit-learn (`requirements-ml.txt`). If your computer blocks them (e.g. a Windows
"Application Control" policy), use Google Colab: open `notebooks/train_air_quality_colab.ipynb`, run it, download `ml_outputs.zip`,
extract into the project root, then `cd backend && python -m scripts.import_ml_outputs --all` (needs no pandas). In production the
GitHub Actions job (Linux) generates forecasts hourly once model files are committed.

## Commands (if your machine allows the ML libraries)
```
# 1. data (backend/, venv active)
python -m scripts.backfill_openaq --days 400
python -m scripts.backfill_weather --days 420
# 2. train (project root, needs: pip install -r requirements-ml.txt)
python -m ml_engine.pollution.train          # add --fast for a quick smoke run
# 3. forecast (backend/)
python -m scripts.run_forecasts
```
Training writes: model files `ml_engine/saved_models/pollution/*.joblib`, `metrics_<version>.json`, registry rows (table `model_registry`) and `docs/ML_REPORT_air_quality.md`.
