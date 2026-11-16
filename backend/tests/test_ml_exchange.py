"""Export/import of ML outputs: needs NO pandas, so it runs even on machines where pandas is blocked."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import Location, ModelRegistry, PollutionPrediction
from ml_engine.pollution.exchange import export_predictions, export_registry, import_file
from scripts.seed import seed

ORIGIN = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)


def new_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False)()
    seed(s)
    s.add(Location(city_id=1, kind="aq_station", source="openaq", external_id="A1", name="Station A", latitude=20.3, longitude=85.8))
    s.commit()
    return s


def test_registry_and_predictions_roundtrip_is_idempotent(tmp_path):
    src, dst = new_db(), new_db()
    for v, active in (("v1", False), ("v2", True)):
        src.add(ModelRegistry(module="pollution", name="pm25_h1", version=v, dataset_version="d", feature_schema=["a", "b"],
                              metrics={"test": {"rmse": 4.2}, "interval": {"level": 0.8}}, baseline_metrics={"persistence": {"rmse": 5.0}},
                              artifact_path="ml_engine/saved_models/pollution/x.joblib", calibration_status="LOCALLY_VALIDATED",
                              trained_on="OBSERVED", is_active=active, notes="n"))
    src.add(PollutionPrediction(location_id=1, made_at=ORIGIN, target_time=ORIGIN + timedelta(hours=1), horizon_h=1, parameter="pm25",
                                predicted_value=55.5, lower=45.0, upper=66.0, trend="stable", index_category="Satisfactory", model_version="v2"))
    src.commit()
    reg, pred = tmp_path / "registry_v2.json", tmp_path / "predictions_x.json"
    assert export_registry(src, reg, version="v2") == 1 and export_predictions(src, pred) == 1
    # destination already has an OLD active version: importing v2 must make v2 the only active one
    dst.add(ModelRegistry(module="pollution", name="pm25_h1", version="v1", is_active=True, trained_at=ORIGIN))
    dst.commit()
    assert import_file(dst, reg) == {"file": "registry_v2.json", "kind": "registry", "added": 1, "updated": 0}
    assert import_file(dst, pred)["added"] == 1
    assert {(r.version, r.is_active) for r in dst.scalars(select(ModelRegistry))} == {("v1", False), ("v2", True)}
    r = dst.scalar(select(ModelRegistry).where(ModelRegistry.version == "v2"))
    assert r.metrics["test"]["rmse"] == 4.2 and r.feature_schema == ["a", "b"] and r.calibration_status == "LOCALLY_VALIDATED"
    p = dst.scalar(select(PollutionPrediction))
    assert p.predicted_value == 55.5 and p.parameter == "pm25"
    again = [import_file(dst, reg), import_file(dst, pred)]                       # second import changes nothing
    assert again[0]["added"] == 0 and again[1]["added"] == 0
    assert dst.scalar(select(func.count(PollutionPrediction.id))) == 1 and dst.scalar(select(func.count(ModelRegistry.id))) == 2


def test_predictions_for_unknown_station_are_skipped(tmp_path):
    src, dst = new_db(), new_db()
    src.add(PollutionPrediction(location_id=1, made_at=ORIGIN, target_time=ORIGIN, horizon_h=1, parameter="pm25", predicted_value=1.0,
                                lower=0.0, upper=2.0, trend="stable", index_category="Good", model_version="v"))
    src.commit()
    f = tmp_path / "p.json"
    export_predictions(src, f)
    dst.delete(dst.scalar(select(Location)))
    dst.commit()
    assert import_file(dst, f)["added"] == 0
