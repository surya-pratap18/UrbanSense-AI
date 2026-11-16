"""Generate and store air-quality forecasts from the latest data (needs `pip install -r requirements-ml.txt`).
   cd backend && python -m scripts.run_forecasts"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ml_engine._bootstrap  # noqa: E402,F401
from app.database.session import SessionLocal  # noqa: E402
from ml_engine.pollution.predict import run_forecasts  # noqa: E402

with SessionLocal() as db:
    res = run_forecasts(db)
print(res)
sys.exit(0 if res["stored"] else 1)
