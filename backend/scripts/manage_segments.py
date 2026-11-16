"""Switch monitored road segments on/off without re-running discovery (no TomTom requests used).
   cd backend
   python -m scripts.manage_segments list
   python -m scripts.manage_segments off 3 7        # stop collecting these ids
   python -m scripts.manage_segments on 3"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database.session import SessionLocal  # noqa: E402
from app.models import RoadSegment  # noqa: E402
from app.services.traffic import segment_props  # noqa: E402

cmd, ids = (sys.argv[1] if len(sys.argv) > 1 else "list"), [int(x) for x in sys.argv[2:]]
with SessionLocal() as db:
    if cmd in ("on", "off"):
        for s in db.scalars(select(RoadSegment).where(RoadSegment.id.in_(ids))):
            s.is_active = cmd == "on"
        db.commit()
    elif cmd != "list":
        sys.exit(__doc__)
    for s in db.scalars(select(RoadSegment).order_by(RoadSegment.id)):
        p = segment_props(s)
        print(f"{s.id:3d} {'ON ' if s.is_active else 'off'} {s.name:38s} {s.road_type:10s} {p.get('frc', '-'):5s} {(p.get('length_m') or 0) / 1000:5.2f} km")
