"""Load model-registry rows and forecasts produced elsewhere (Colab) into the database this app serves from.
   cd backend
   python -m scripts.import_ml_outputs --all                     # every registry_*.json then predictions_*.json found
   python -m scripts.import_ml_outputs path/to/file.json ...
No pandas needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ml_engine._bootstrap  # noqa: E402,F401
from app.database.session import SessionLocal  # noqa: E402
from ml_engine.pollution.exchange import SAVE_DIR, import_file  # noqa: E402

args = sys.argv[1:]
if args == ["--all"]:
    files = sorted(SAVE_DIR.glob("registry_*.json")) + sorted(SAVE_DIR.glob("predictions_*.json"))
else:
    files = [Path(a) for a in args]
if not files:
    sys.exit(f"No files found. Looked in {SAVE_DIR}")
with SessionLocal() as db:
    for f in files:
        print(import_file(db, f))
