"""Move ML outputs between machines WITHOUT pandas/xgboost (so it runs on a locked-down laptop).
 Colab (trains + forecasts)  --registry_*.json / predictions_*.json-->  your local or Supabase database.
   python -m ml_engine.pollution.exchange export-predictions <file.json>     (run where forecasts were generated)
   cd backend && python -m scripts.import_ml_outputs --all                   (run where the database you serve from lives)
Importing is idempotent: running it twice changes nothing."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ml_engine._bootstrap  # noqa: F401
from sqlalchemy import select

from app.core.datastate import as_utc
from app.models import Location, ModelRegistry, PollutionPrediction

ROOT = Path(__file__).resolve().parents[2]
SAVE_DIR = ROOT / "ml_engine" / "saved_models" / "pollution"
REG_COLS = ["module", "name", "version", "dataset_version", "feature_schema", "metrics", "baseline_metrics",
            "artifact_path", "calibration_status", "trained_on", "is_active", "notes"]


def _iso(d):
    return as_utc(d).isoformat() if d else None


def _dt(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc) if s else None


def export_registry(db, path: Path, version: str | None = None) -> int:
    q = select(ModelRegistry).where(ModelRegistry.module == "pollution")
    q = q.where(ModelRegistry.version == version) if version else q.where(ModelRegistry.is_active.is_(True))
    rows = [{**{c: getattr(r, c) for c in REG_COLS}, "trained_at": _iso(r.trained_at)} for r in db.scalars(q)]
    Path(path).write_text(json.dumps({"kind": "registry", "rows": rows}, indent=1, default=str))
    return len(rows)


def export_predictions(db, path: Path, hours: int = 72) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    ext = {l.id: l.external_id for l in db.scalars(select(Location))}
    rows = [{"station_external_id": ext[p.location_id], "parameter": p.parameter, "horizon_h": p.horizon_h,
             "made_at": _iso(p.made_at), "target_time": _iso(p.target_time), "predicted_value": p.predicted_value,
             "lower": p.lower, "upper": p.upper, "trend": p.trend, "index_category": p.index_category,
             "model_version": p.model_version}
            for p in db.scalars(select(PollutionPrediction).where(PollutionPrediction.made_at >= since))]
    Path(path).write_text(json.dumps({"kind": "predictions", "rows": rows}, indent=1))
    return len(rows)


def import_file(db, path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    added = updated = 0
    if data["kind"] == "registry":
        for r in data["rows"]:
            obj = db.scalar(select(ModelRegistry).where(ModelRegistry.module == r["module"], ModelRegistry.name == r["name"],
                                                        ModelRegistry.version == r["version"]))
            vals = {c: r[c] for c in REG_COLS}
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                updated += 1
            else:
                obj = ModelRegistry(trained_at=_dt(r["trained_at"]), **vals)
                db.add(obj)
                added += 1
            if r["is_active"]:       # the imported version becomes the single active one for that model name
                for old in db.scalars(select(ModelRegistry).where(ModelRegistry.module == r["module"], ModelRegistry.name == r["name"],
                                                                  ModelRegistry.version != r["version"], ModelRegistry.is_active.is_(True))):
                    old.is_active = False
    elif data["kind"] == "predictions":
        locs = {l.external_id: l.id for l in db.scalars(select(Location).where(Location.source == "openaq"))}
        for r in data["rows"]:
            lid = locs.get(r["station_external_id"])
            if lid is None:
                continue          # station not in this database (run the OpenAQ backfill/collector first)
            made = _dt(r["made_at"])
            obj = db.scalar(select(PollutionPrediction).where(PollutionPrediction.location_id == lid, PollutionPrediction.made_at == made,
                                                              PollutionPrediction.horizon_h == r["horizon_h"], PollutionPrediction.parameter == r["parameter"]))
            vals = dict(target_time=_dt(r["target_time"]), predicted_value=r["predicted_value"], lower=r["lower"], upper=r["upper"],
                        trend=r["trend"], index_category=r["index_category"], model_version=r["model_version"])
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                updated += 1
            else:
                db.add(PollutionPrediction(location_id=lid, made_at=made, horizon_h=r["horizon_h"], parameter=r["parameter"], **vals))
                added += 1
    else:
        raise ValueError(f"Unknown file kind: {data.get('kind')}")
    db.commit()
    return {"file": Path(path).name, "kind": data["kind"], "added": added, "updated": updated}


if __name__ == "__main__":
    from app.database.session import SessionLocal
    if len(sys.argv) == 3 and sys.argv[1] == "export-predictions":
        with SessionLocal() as db:
            print("predictions exported:", export_predictions(db, Path(sys.argv[2])))
    else:
        sys.exit(__doc__)
