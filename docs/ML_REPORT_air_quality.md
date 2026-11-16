# Air-quality forecasting: evaluation report

Version `20261116-0742`  |  data: openaq:2025-10-11 10:30:00..2026-11-16 04:30:00:rows=19238

Train up to 2026-07-18T23:30:00 UTC, validation up to 2026-09-17T02:30:00 UTC, test afterwards; 6 h embargo between parts.
All numbers come from the held-out TEST period. Units: ug/m3. Skill = 1 - RMSE(model)/RMSE(persistence).

| Target | Model | Test MAE | Test RMSE | R2 | Persistence RMSE | Hour-of-day RMSE | Skill | 80% interval coverage | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| pm25_h1 | random_forest | 3.9381 | 15.4994 | 0.739 | 14.1402 | 41.5546 | -0.0961 | 0.8571 | NO_SKILL_OVER_BASELINE |
| pm25_h3 | xgboost_d6 | 10.4152 | 23.987 | 0.3407 | 29.459 | 40.9745 | 0.1857 | 0.7256 | LOCALLY_VALIDATED |
| pm25_h6 | xgboost_d4 | 13.1929 | 29.7173 | 0.2701 | 36.3666 | 44.3674 | 0.1828 | 0.6776 | LOCALLY_VALIDATED |
| pm10_h1 | xgboost_d4 | 7.1591 | 12.5597 | 0.9055 | 15.5651 | 65.6255 | 0.1931 | 0.8551 | LOCALLY_VALIDATED |
| pm10_h3 | xgboost_d4 | 15.9504 | 29.954 | 0.435 | 35.9257 | 65.1482 | 0.1662 | 0.778 | LOCALLY_VALIDATED |
| pm10_h6 | xgboost_d4 | 20.528 | 36.6134 | 0.2887 | 45.5664 | 66.9978 | 0.1965 | 0.7269 | LOCALLY_VALIDATED |

A verdict of NO_SKILL_OVER_BASELINE means a simple baseline was at least as good; the app labels such forecasts accordingly.
