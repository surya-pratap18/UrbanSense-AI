"""Air-quality forecasting: train, evaluate honestly, register.

  cd <project root>   python -m ml_engine.pollution.train [--fast]

Method
 - Chronological split 70/15/15 by time (all stations share the cut-off dates), with a 6-hour embargo gap between
   parts so no training target overlaps validation/test features.
 - Baselines: persistence (value now) and hour-of-day mean (from training data only).
 - Candidates: XGBoost (2 settings, early stopping on validation) and Random Forest. Winner = lowest validation RMSE.
 - Metrics (MAE, RMSE, R2, MAPE on targets >= 10) are computed on the held-out TEST part only, on rows where the
   current value exists, identically for the model and the baselines.
 - 80 % prediction interval: split-conformal width from validation residuals, coverage re-checked on test.
 - A model that does not beat the best baseline on test is still saved but flagged NO_SKILL_OVER_BASELINE."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import ml_engine._bootstrap  # noqa: F401
from ml_engine.evaluation.metrics import regression_metrics
from ml_engine.pollution.data import station_codes, station_tables, training_frame
from ml_engine.preprocessing.air_quality import TZ

ROOT = Path(__file__).resolve().parents[2]
SAVE_DIR = ROOT / "ml_engine" / "saved_models" / "pollution"
GAP_HOURS = 6
INTERVAL_LEVEL = 0.80


def chronological_split(index: pd.DatetimeIndex, gap_hours: int = GAP_HOURS):
    idx = index.tz_convert("UTC").tz_localize(None).values          # datetime64[ns]
    times = np.unique(idx)
    t1, t2 = times[int(len(times) * 0.70)], times[int(len(times) * 0.85)]
    gap = np.timedelta64(gap_hours, "h")
    return (idx <= t1 - gap), ((idx > t1) & (idx <= t2 - gap)), (idx > t2), (t1, t2)


def _candidates(fast: bool):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from xgboost import XGBRegressor
    n = 60 if fast else 600
    xgb = lambda **kw: XGBRegressor(n_estimators=n, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=5,  # noqa: E731
                                    early_stopping_rounds=30, eval_metric="rmse", n_jobs=-1, random_state=42, **kw)
    return {"xgboost_d4": ("xgb", xgb(max_depth=4)), "xgboost_d6": ("xgb", xgb(max_depth=6)),
            "random_forest": ("rf", make_pipeline(SimpleImputer(strategy="median"),
                                                  RandomForestRegressor(n_estimators=30 if fast else 200, max_depth=12, min_samples_leaf=10,
                                                                        max_features=0.5, n_jobs=-1, random_state=42)))}


def _hod_baseline(train: pd.DataFrame, ycol: str, h: int):
    """Mean target by (station, local hour of the TARGET time), learned from training rows only."""
    tgt_hour = (train.index + pd.Timedelta(hours=h)).tz_convert(TZ).hour
    s = train[ycol].groupby([train["station_key"].values, tgt_hour]).mean()
    return s, lambda df: np.array([s.get((k, hr), np.nan) for k, hr in zip(
        df["station_key"].values, (df.index + pd.Timedelta(hours=h)).tz_convert(TZ).hour)])


def train_one(frame: pd.DataFrame, feats: list[str], target: str, h: int, masks, fast: bool, codes: dict) -> tuple[dict, dict]:
    ycol, cur = f"y_{target}_h{h}", f"{target}_lag0"
    ok = frame[ycol].notna()
    tr, va, te = (frame[ok & m] for m in masks)
    if min(len(tr), len(va), len(te)) < 50:
        raise RuntimeError(f"Not enough rows for {target} h{h} (train {len(tr)}, val {len(va)}, test {len(te)}). Backfill more history.")
    _, hod = _hod_baseline(tr, ycol, h)
    comp = lambda d: d[d[cur].notna()]  # noqa: E731  (fair comparison rows: current value known)
    fitted = {}
    for name, (kind, model) in _candidates(fast).items():
        if kind == "xgb":
            model.fit(tr[feats], tr[ycol], eval_set=[(va[feats], va[ycol])], verbose=False)
        else:
            model.fit(tr[feats], tr[ycol])
        v = comp(va)
        fitted[name] = (model, regression_metrics(v[ycol], model.predict(v[feats]))["rmse"])
    best = min(fitted, key=lambda k: fitted[k][1])
    model = fitted[best][0]
    v, t = comp(va), comp(te)
    pv, pt = model.predict(v[feats]), model.predict(t[feats])
    n = len(v)
    q = float(np.quantile(np.abs(v[ycol].values - pv), min(1.0, INTERVAL_LEVEL * (1 + 1 / n))))
    cover = float(np.mean(np.abs(t[ycol].values - pt) <= q))
    m_val, m_test = regression_metrics(v[ycol], pv), regression_metrics(t[ycol], pt)
    base = {"persistence": regression_metrics(t[ycol], t[cur]), "hour_of_day_mean": regression_metrics(t[ycol], hod(t))}
    best_base = min((b["rmse"] for b in base.values() if b["rmse"] is not None), default=None)
    skill = None if not best_base else round(1 - m_test["rmse"] / base["persistence"]["rmse"], 4)
    beats = best_base is not None and m_test["rmse"] < best_base
    per_station = {s: regression_metrics(g[ycol], model.predict(g[feats])) for s, g in t.groupby("station_key")}
    imp = getattr(model, "feature_importances_", None)
    top = sorted(zip(feats, imp), key=lambda x: -x[1])[:10] if imp is not None else None
    metrics = {"model_type": best, "val": m_val, "test": m_test, "test_per_station": per_station,
               "interval": {"level": INTERVAL_LEVEL, "halfwidth": round(q, 3), "test_coverage": round(cover, 4)},
               "skill_vs_persistence": skill, "beats_baseline": bool(beats),
               "candidate_val_rmse": {k: v_[1] for k, v_ in fitted.items()},
               "rows": {"train": len(tr), "val": len(va), "test": len(te)},
               "top_features": [(f, round(float(i), 4)) for f, i in top] if top else None}
    artifact = {"model": model, "feature_columns": feats, "interval_halfwidth": q, "interval_level": INTERVAL_LEVEL,
                "target": target, "horizon_h": h, "station_codes": codes, "model_type": best}
    return artifact, {"metrics": metrics, "baselines": base}


def run(db, *, targets=("pm25", "pm10"), horizons=(1, 3, 6), fast=False, out_dir: Path | None = None,
        register=True, version: str | None = None) -> dict:
    from app.models import ModelRegistry
    out_dir = Path(out_dir or SAVE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    codes = station_codes(db)
    tables = station_tables(db)
    if not tables:
        raise RuntimeError("No air-quality data in the database. Run: python -m scripts.backfill_openaq --days 400")
    frame = training_frame(tables, codes, targets, horizons)
    feats = [c for c in frame.columns if not c.startswith("y_") and c != "station_key"]
    masks = chronological_split(frame.index)
    split_info = {"train_end": str(masks[3][0])[:19], "val_end": str(masks[3][1])[:19], "gap_hours": GAP_HOURS,
                  "first_obs": str(frame.index.min())[:19], "last_obs": str(frame.index.max())[:19]}
    dataset_version = f"openaq:{split_info['first_obs']}..{split_info['last_obs']}:rows={len(frame)}"
    results = {}
    for target in targets:
        for h in horizons:
            art, res = train_one(frame, feats, target, h, masks[:3], fast, codes)
            name = f"{target}_h{h}"
            path = out_dir / f"{name}_{version}.joblib"
            joblib.dump(art, path, compress=3)
            skill_ok = res["metrics"]["beats_baseline"]
            res["metrics"]["split"] = split_info
            res["artifact"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            res["calibration_status"] = "LOCALLY_VALIDATED" if skill_ok else "NO_SKILL_OVER_BASELINE"
            results[name] = res
            if register:
                for old in db.query(ModelRegistry).filter_by(module="pollution", name=name, is_active=True):
                    old.is_active = False
                db.add(ModelRegistry(module="pollution", name=name, version=version, dataset_version=dataset_version,
                                     feature_schema=feats, metrics=res["metrics"], baseline_metrics=res["baselines"],
                                     artifact_path=res["artifact"], calibration_status=res["calibration_status"],
                                     trained_on="OBSERVED", is_active=True,
                                     notes=f"{art['model_type']}; train-only fit evaluated on held-out test period"))
                db.commit()
            m = res["metrics"]
            print(f"{name:9s} {art['model_type']:14s} test RMSE {m['test']['rmse']}  persistence {res['baselines']['persistence']['rmse']}"
                  f"  hod {res['baselines']['hour_of_day_mean']['rmse']}  skill {m['skill_vs_persistence']}  "
                  f"cover80 {m['interval']['test_coverage']}  -> {res['calibration_status']}")
    if register:
        from ml_engine.pollution.exchange import export_registry
        export_registry(db, out_dir / f"registry_{version}.json", version=version)   # portable copy for importing elsewhere
    (out_dir / f"metrics_{version}.json").write_text(json.dumps({"version": version, "dataset": dataset_version, "split": split_info,
                                                                 "results": results}, indent=2, default=str))
    return {"version": version, "dataset_version": dataset_version, "split": split_info, "results": results}


def write_report(summary: dict, path: Path):
    s = summary["split"]
    L = [f"# Air-quality forecasting: evaluation report", f"\nVersion `{summary['version']}`  |  data: {summary['dataset_version']}",
         f"\nTrain up to {s['train_end']} UTC, validation up to {s['val_end']} UTC, test afterwards; {s['gap_hours']} h embargo between parts.",
         "All numbers come from the held-out TEST period. Units: ug/m3. Skill = 1 - RMSE(model)/RMSE(persistence).\n",
         "| Target | Model | Test MAE | Test RMSE | R2 | Persistence RMSE | Hour-of-day RMSE | Skill | 80% interval coverage | Verdict |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in summary["results"].items():
        m, b = r["metrics"], r["baselines"]
        L.append(f"| {name} | {m['model_type']} | {m['test']['mae']} | {m['test']['rmse']} | {m['test']['r2']} | {b['persistence']['rmse']} | "
                 f"{b['hour_of_day_mean']['rmse']} | {m['skill_vs_persistence']} | {m['interval']['test_coverage']} | {r['calibration_status']} |")
    L.append("\nA verdict of NO_SKILL_OVER_BASELINE means a simple baseline was at least as good; the app labels such forecasts accordingly.")
    path.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    from app.database.session import SessionLocal
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="small models, for a quick smoke run")
    a = ap.parse_args()
    with SessionLocal() as db:
        summary = run(db, fast=a.fast)
    write_report(summary, ROOT / "docs" / "ML_REPORT_air_quality.md")
    print("Report written to docs/ML_REPORT_air_quality.md")
