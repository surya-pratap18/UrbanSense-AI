"""ML pipeline tests. SYNTHETIC data is used ONLY here, inside the test database, to prove the code works."""
from datetime import datetime, timedelta, timezone

import pytest

# ML libraries can be blocked by OS security policy on some machines: skip (not fail) in that case
pytest.importorskip("pandas", exc_type=ImportError)
pytest.importorskip("xgboost", exc_type=ImportError)
pytest.importorskip("sklearn", exc_type=ImportError)

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sqlalchemy import func, select

import ml_engine._bootstrap  # noqa: F401
from app.models import Location, ModelRegistry, PollutionObservation, PollutionPrediction, WeatherObservation
from ml_engine.evaluation.metrics import regression_metrics
from ml_engine.pollution import predict, train
from ml_engine.preprocessing.air_quality import attach_weather, build_features, long_to_wide, regularize

NOW = datetime.now(timezone.utc).replace(microsecond=0, second=0)
END = (NOW - timedelta(hours=1)).replace(minute=30)       # hour-end timestamps sit at :30 UTC like the real stations
DAYS = 45


def synth_station(db, ext, seed, name):
    rng = np.random.default_rng(seed)
    loc = Location(city_id=1, kind="aq_station", source="openaq", external_id=ext, name=name, latitude=20.3, longitude=85.8)
    db.add(loc)
    db.commit()
    n = DAYS * 24
    times = [END - timedelta(hours=n - 1 - i) for i in range(n)]
    ar, rows = 0.0, []
    for i, t in enumerate(times):
        ar = 0.9 * ar + rng.normal(0, 6)
        hr = (t + timedelta(hours=5, minutes=30)).hour
        pm25 = max(5.0, 60 + 25 * np.sin(2 * np.pi * (hr - 6) / 24) + ar)
        vals = {"pm25": pm25, "pm10": 1.6 * pm25 + rng.normal(0, 5), "no2": 15 + rng.normal(0, 2), "so2": 5 + rng.normal(0, 1),
                "co": 600 + rng.normal(0, 50), "o3": 40 + rng.normal(0, 5), "temperature": 28 + 4 * np.sin(2 * np.pi * hr / 24),
                "relativehumidity": 70 + rng.normal(0, 3), "wind_speed": abs(rng.normal(2, 1)), "wind_direction": rng.uniform(0, 360)}
        for p, v in vals.items():
            if p == "pm25" and (rng.random() < 0.03 or 300 < i < 312):      # random gaps + one 12 h outage: genuinely missing
                continue
            rows.append(PollutionObservation(location_id=loc.id, observed_at=t, parameter=p, value=float(v),
                                             unit="ppb" if p in ("no2", "so2", "co") else "x", source="openaq"))
    db.add_all(rows)
    db.commit()
    return loc


def synth_weather(db):
    rng = np.random.default_rng(1)
    start = (END - timedelta(days=DAYS + 3)).replace(minute=0)
    db.add_all([WeatherObservation(city_id=1, valid_at=start + timedelta(hours=i), is_forecast=False, latitude=20.3, longitude=85.8,
                                   rainfall_mm=float(max(0, rng.normal(-0.5, 1))), cloud_cover_pct=50.0, source="open_meteo_archive")
                for i in range((DAYS + 4) * 24)])
    db.commit()


@pytest.fixture()
def ml_db(db):
    synth_weather(db)
    synth_station(db, "A1", 10, "Station A")
    synth_station(db, "B2", 11, "Station B")
    return db


# ---------- correctness of the method ----------
def test_features_never_look_ahead(ml_db):
    from ml_engine.pollution.data import station_tables
    w = station_tables(ml_db)["A1"]
    k = 600
    X1 = build_features(w, 0)
    w2 = w.copy()
    w2.iloc[k + 1:] = w2.iloc[k + 1:] * 3 + 7                      # corrupt EVERYTHING after row k (incl. weather columns)
    X2 = build_features(w2, 0)
    assert_frame_equal(X1.iloc[:k + 1], X2.iloc[:k + 1])           # rows <= k must be untouched


def test_missing_hours_stay_missing_not_zero(ml_db):
    from ml_engine.pollution.data import station_tables
    w = station_tables(ml_db)["A1"]
    assert w["pm25"].isna().sum() >= 12 and (w["pm25"].dropna() > 0).all()
    assert len(w) == DAYS * 24                                     # regular grid, no hours dropped


def test_split_is_chronological_with_embargo():
    idx = pd.date_range("2026-01-01", periods=2000, freq="1h", tz="UTC").append(pd.date_range("2026-01-01", periods=2000, freq="1h", tz="UTC"))
    tr, va, te, _ = train.chronological_split(idx)
    assert not (tr & va).any() and not (va & te).any() and not (tr & te).any()
    iv = idx.tz_localize(None).values
    gap = np.timedelta64(6, "h")
    assert iv[tr].max() + gap <= iv[va].min() and iv[va].max() + gap <= iv[te].min()
    assert abs(tr.sum() / len(idx) - 0.70) < 0.05


def test_metrics_known_values():
    m = regression_metrics([10, 20, 30], [12, 18, 33])
    assert m["mae"] == pytest.approx(2.3333, abs=1e-3) and m["rmse"] == pytest.approx(2.3805, abs=1e-3)
    assert regression_metrics([1, 2, 3], [1, 2, 3])["r2"] == 1.0
    assert regression_metrics([], [])["n"] == 0
    assert regression_metrics([1, 2, 3], [1, 2, float("nan")])["n"] == 2   # NaN rows ignored, not zero-filled


# ---------- full pipeline ----------
def test_train_register_forecast_and_serve(ml_db, client, tmp_path):
    db = ml_db
    summary = train.run(db, fast=True, out_dir=tmp_path)
    assert set(summary["results"]) == {f"{t}_h{h}" for t in ("pm25", "pm10") for h in (1, 3, 6)}
    for name, r in summary["results"].items():
        m = r["metrics"]
        assert m["test"]["rmse"] and m["test"]["n"] >= 50 and r["baselines"]["persistence"]["rmse"]
        assert 0.6 <= m["interval"]["test_coverage"] <= 0.97           # 80% conformal interval is roughly honest on test
        assert r["calibration_status"] in ("LOCALLY_VALIDATED", "NO_SKILL_OVER_BASELINE")
        assert (tmp_path / f"{name}_{summary['version']}.joblib").exists()
    train.write_report(summary, tmp_path / "report.md")
    assert "held-out TEST" in (tmp_path / "report.md").read_text()
    assert db.scalar(select(func.count(ModelRegistry.id)).where(ModelRegistry.is_active.is_(True))) == 6

    res = predict.run_forecasts(db, now=NOW)
    assert res["stored"] == 12 and res["skipped"] == []                # 2 stations x 2 targets x 3 horizons
    n_before = db.scalar(select(func.count(PollutionPrediction.id)))
    assert predict.run_forecasts(db, now=NOW)["stored"] == 12
    assert db.scalar(select(func.count(PollutionPrediction.id))) == n_before   # idempotent per forecast origin
    for p in db.scalars(select(PollutionPrediction)):
        assert 0 <= p.lower <= p.predicted_value <= p.upper
        assert p.target_time - p.made_at == timedelta(hours=p.horizon_h)
    stale = predict.run_forecasts(db, now=NOW + timedelta(hours=10))
    assert stale["stored"] == 0 and len(stale["skipped"]) == 12        # never forecast from stale data

    r = client.get("/api/pollution/predictions").json()
    assert len(r["data"]) == 2 and r["data"][0]["input_data_state"] == "LIVE"
    f = r["data"][0]["forecasts"]
    assert len(f) == 6 and {x["horizon_h"] for x in f} == {1, 3, 6}
    assert all(x["model_status"] in ("LOCALLY_VALIDATED", "NO_SKILL_OVER_BASELINE") and x["test_rmse"] for x in f)
    assert client.get("/api/pollution/predictions?station_id=999").status_code == 404

    assert client.get("/api/models/metrics").status_code == 401        # registry requires login
    tok = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpass1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    mm = client.get("/api/models/metrics?module=pollution", headers=h).json()
    assert mm["meta"]["count"] == 6 and mm["data"][0]["metrics"]["test"]["rmse"]
    assert client.get("/api/models?module=pollution&active_only=true", headers=h).json()["meta"]["total"] == 6


def test_retraining_deactivates_old_versions(ml_db, tmp_path):
    train.run(ml_db, fast=True, out_dir=tmp_path, version="v1", horizons=(1,), targets=("pm25",))
    train.run(ml_db, fast=True, out_dir=tmp_path, version="v2", horizons=(1,), targets=("pm25",))
    rows = ml_db.scalars(select(ModelRegistry).where(ModelRegistry.name == "pm25_h1").order_by(ModelRegistry.id)).all()
    assert [(r.version, r.is_active) for r in rows] == [("v1", False), ("v2", True)]


def test_clear_error_when_no_data(db, tmp_path):
    with pytest.raises(RuntimeError, match="backfill_openaq"):
        train.run(db, fast=True, out_dir=tmp_path)
