"""One pipeline for every source: run collector -> update data_source_status (attempt/success/error/failures)."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.open_meteo import collect_weather
from app.collectors.openaq import collect_openaq
from app.collectors.tomtom import collect_tomtom
from app.core.config import get_settings
from app.models import DataSourceStatus

log = logging.getLogger("ingestion")

# public name -> (source_key in data_source_status, callable(db) -> records)
COLLECTORS = {
    "weather": ("open_meteo", lambda db: collect_weather(db, get_settings().city_slug)),
    "air-quality": ("openaq", lambda db: collect_openaq(db, get_settings().city_slug)),
    "traffic": ("tomtom_traffic", lambda db: collect_tomtom(db, get_settings().city_slug)),
}
NOT_BUILT_YET: set[str] = set()  # all collectors are built


def run_collector(db: Session, name: str) -> dict:
    source_key, fn = COLLECTORS[name]
    status = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == source_key))
    if status is None:
        raise RuntimeError(f"Source '{source_key}' not seeded: run `python -m scripts.seed`")
    status.last_attempt_at = datetime.now(timezone.utc)
    db.commit()
    try:
        n = fn(db)
    except Exception as e:  # noqa: BLE001: any failure must be recorded, not crash the scheduler
        db.rollback()
        status = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == source_key))
        status.consecutive_failures = (status.consecutive_failures or 0) + 1
        status.last_error = f"{type(e).__name__}: {e}"[:500]
        db.commit()
        log.error("Collector %s failed: %s", name, status.last_error)
        return {"ok": False, "source": source_key, "error": status.last_error}
    status.last_success_at = datetime.now(timezone.utc)
    status.consecutive_failures = 0
    status.last_error = None
    status.records_last_run = n
    db.commit()
    return {"ok": True, "source": source_key, "records": n}
