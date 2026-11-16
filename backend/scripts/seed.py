"""Create tables, seed the city + data sources, create the first admin.
Run from the backend/ folder:  python -m scripts.seed
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.sources import SOURCES  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.models import City, DataSourceStatus, User  # noqa: E402


def seed(db):
    s = get_settings()
    if not db.scalar(select(City).where(City.slug == "bhubaneswar")):
        db.add(City(slug="bhubaneswar", name="Bhubaneswar", state="Odisha", latitude=20.2961, longitude=85.8245))
    for src in SOURCES:
        row = db.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == src["source_key"]))
        if row:
            for k, v in src.items():
                setattr(row, k, v)
        else:
            db.add(DataSourceStatus(**src))
    email = s.admin_email or "admin@example.com"
    password = s.admin_password
    if not db.scalar(select(User).where(User.email == email.lower())):
        if len(password) < 8:
            print("!! ADMIN_PASSWORD missing/too short (min 8) in .env -> admin NOT created")
        else:
            db.add(User(email=email.lower(), hashed_password=hash_password(password), full_name="Administrator", role="admin"))
            print(f"Admin created: {email}")
    db.commit()


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    print("Database ready:", engine.url.render_as_string(hide_password=True))
