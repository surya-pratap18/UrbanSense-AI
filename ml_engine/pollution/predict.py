"""Inference: load the ACTIVE registered models, build features with the same code as training, store forecasts.
Runs outside the web request (scheduled job / script). The API only reads the stored forecasts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import select

import ml_engine._bootstrap  # noqa: F401
from app.core.datastate import as_utc
from app.models import Location, ModelRegistry, PollutionPrediction
from app.services.aqi import category, sub_index
from ml_engine.pollution.data import station_tables
from ml_engine.preprocessing.air_quality import build_features

ROOT = Path(__file__).resolve().parents[2]
LOOKBACK_HOURS = 120          # enough for lag24 / rolling24 with margin
MAX_ORIGIN_AGE_H = 6          # do not forecast from data older than this


def load_active_models(db) -> dict:
    out = {}
    for r in db.scalars(select(ModelRegistry).where(ModelRegistry.module == "pollution", ModelRegistry.is_active.is_(True))):
        path = Path(r.artifact_path)
        path = path if path.is_absolute() else ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"Model artifact missing: {path}. Commit ml_engine/saved_models/ or retrain.")
        art = joblib.load(path)
        out[(art["target"], art["horizon_h"])] = (r, art)
    return out


def _trend(pred: float, current: float) -> str:
    d = pred - current
    return "stable" if abs(d) < max(3.0, 0.10 * current) else ("rising" if d > 0 else "falling")


def run_forecasts(db, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    models = load_active_models(db)
    if not models:
        raise RuntimeError("No active pollution models. Train first: python -m ml_engine.pollution.train")
    tables = station_tables(db, since=now - timedelta(hours=LOOKBACK_HOURS))
    locs = {l.external_id: l for l in db.scalars(select(Location).where(Location.kind == "aq_station", Location.source == "openaq"))}
    stored, skipped = 0, []
    for ext, w in tables.items():
        for (target, h), (reg, art) in sorted(models.items()):
            if ext not in art["station_codes"]:
                skipped.append(f"{ext}/{target}/h{h}: station unknown to model")
                continue
            valid = w.index[w[target].notna()]
            if len(valid) == 0:
                skipped.append(f"{ext}/{target}/h{h}: no {target} data")
                continue
            origin = valid[-1]
            if (now - origin.to_pydatetime()).total_seconds() > MAX_ORIGIN_AGE_H * 3600:
                skipped.append(f"{ext}/{target}/h{h}: latest data too old ({origin})")
                continue
            X = build_features(w, art["station_codes"][ext])
            row = X.loc[[origin], art["feature_columns"]]
            pred = max(0.0, float(art["model"].predict(row)[0]))
            hw = float(art["interval_halfwidth"])
            cur = float(w.at[origin, target])
            target_time = origin.to_pydatetime() + timedelta(hours=h)
            made_at = origin.to_pydatetime()
            cat = category(sub_index(target, pred)) if target in ("pm25", "pm10") else None
            obj = db.scalar(select(PollutionPrediction).where(
                PollutionPrediction.location_id == locs[ext].id, PollutionPrediction.made_at == made_at,
                PollutionPrediction.horizon_h == h, PollutionPrediction.parameter == target))
            vals = dict(target_time=target_time, predicted_value=round(pred, 2), lower=round(max(0.0, pred - hw), 2),
                        upper=round(pred + hw, 2), trend=_trend(pred, cur), index_category=cat, model_version=reg.version)
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
            else:
                db.add(PollutionPrediction(location_id=locs[ext].id, made_at=made_at, horizon_h=h, parameter=target, **vals))
            stored += 1
    db.commit()
    return {"stored": stored, "skipped": skipped}
