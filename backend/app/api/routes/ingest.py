from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_cron_or_admin
from app.core.config import get_settings
from app.core.datastate import as_utc
from app.database.session import get_db
from app.models import DataSourceStatus
from app.services.ingestion import COLLECTORS, NOT_BUILT_YET, run_collector
from app.utils.responses import ok

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])


@router.post("/{name}")
def ingest(name: str, actor: str = Depends(require_cron_or_admin), db: Session = Depends(get_db)):
    """Trigger one collection run. Scheduler uses header X-Cron-Secret; admins use their JWT.
    Admin/manual refreshes have a cooldown so nobody can burn the free API quotas."""
    if name in NOT_BUILT_YET:
        raise HTTPException(501, f"Collector '{name}' is not built yet")
    if name not in COLLECTORS:
        raise HTTPException(404, f"Unknown collector '{name}'. Available: {', '.join(COLLECTORS)}")
    if actor != "cron":
        st = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == COLLECTORS[name][0]))
        cooldown = get_settings().refresh_cooldown_seconds
        if st and st.last_attempt_at:
            elapsed = (datetime.now(timezone.utc) - as_utc(st.last_attempt_at)).total_seconds()
            if elapsed < cooldown:
                wait = int(cooldown - elapsed) + 1
                raise HTTPException(429, f"Refreshed recently. Try again in {wait}s.", headers={"Retry-After": str(wait)})
    result = run_collector(db, name)
    return ok(result)
