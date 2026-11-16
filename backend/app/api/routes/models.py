from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.datastate import as_utc
from app.database.session import get_db
from app.models import ModelRegistry
from app.utils.responses import ok

router = APIRouter(prefix="/api/models", tags=["Models"], dependencies=[Depends(get_current_user)])


def _row(r: ModelRegistry, with_metrics=False) -> dict:
    d = {"id": r.id, "module": r.module, "name": r.name, "version": r.version, "dataset_version": r.dataset_version,
         "trained_at": as_utc(r.trained_at).isoformat(), "trained_on": r.trained_on, "is_active": r.is_active,
         "calibration_status": r.calibration_status, "artifact_path": r.artifact_path, "notes": r.notes}
    if with_metrics:
        d.update(metrics=r.metrics, baseline_metrics=r.baseline_metrics, feature_schema=r.feature_schema)
    return d


@router.get("")
def list_models(module: str | None = Query(None, pattern="^(traffic|pollution|waste)$"), active_only: bool = False,
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    q = select(ModelRegistry)
    if module:
        q = q.where(ModelRegistry.module == module)
    if active_only:
        q = q.where(ModelRegistry.is_active.is_(True))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(ModelRegistry.trained_at.desc(), ModelRegistry.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return ok([_row(r) for r in rows], page=page, page_size=page_size, total=total)


@router.get("/metrics")
def metrics(module: str | None = Query(None, pattern="^(traffic|pollution|waste)$"), db: Session = Depends(get_db)):
    """Real held-out test metrics of the ACTIVE models, with baselines. Nothing here is typed in by hand."""
    q = select(ModelRegistry).where(ModelRegistry.is_active.is_(True))
    if module:
        q = q.where(ModelRegistry.module == module)
    rows = db.scalars(q.order_by(ModelRegistry.module, ModelRegistry.name)).all()
    return ok([_row(r, with_metrics=True) for r in rows], count=len(rows))
