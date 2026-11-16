from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.data_status import source_rows
from app.utils.responses import ok

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/data-status")
def data_status(db: Session = Depends(get_db)):
    """Public: freshness state (LIVE/DELAYED/HISTORICAL/SIMULATED/UNAVAILABLE) of every data source."""
    rows = source_rows(db)
    return ok(rows, count=len(rows))
