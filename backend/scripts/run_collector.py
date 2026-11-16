"""Run one collector from the command line (also used by GitHub Actions).
   cd backend && python -m scripts.run_collector weather
Exit code 1 on failure so the scheduled job shows red."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import SessionLocal  # noqa: E402
from app.services.ingestion import COLLECTORS, run_collector  # noqa: E402

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COLLECTORS:
        print(f"Usage: python -m scripts.run_collector <{'|'.join(COLLECTORS)}>")
        sys.exit(2)
    with SessionLocal() as db:
        result = run_collector(db, name)
    print(result)
    sys.exit(0 if result["ok"] else 1)
