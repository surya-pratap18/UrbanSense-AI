"""Write the PostgreSQL DDL to docs/schema_postgres.sql (run from backend/)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.database.base import Base  # noqa: E402
import app.models  # noqa: E402,F401

out = ["-- UrbanSense AI: PostgreSQL schema (generated from SQLAlchemy models)\n"]
for t in Base.metadata.sorted_tables:
    out.append(str(CreateTable(t).compile(dialect=postgresql.dialect())).strip() + ";\n")
    for ix in sorted(t.indexes, key=lambda i: i.name):
        out.append(str(CreateIndex(ix).compile(dialect=postgresql.dialect())).strip() + ";\n")
dest = Path(__file__).resolve().parents[2] / "docs" / "schema_postgres.sql"
dest.write_text("\n".join(out))
print("wrote", dest, "-", len(Base.metadata.sorted_tables), "tables")
