"""
pytest conftest — patches the SQLAlchemy engine to use SQLite in-memory
(with StaticPool so all connections share the same instance)
before any test module imports the FastAPI app.

This avoids needing a running Postgres server for local unit/integration tests.
"""
from __future__ import annotations

from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# 1. Replace JSONB with JSON in the SQLAlchemy dialect so SQLite can compile
# ---------------------------------------------------------------------------
import sqlalchemy.dialects.postgresql as _pg
_pg.JSONB = JSON  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# 2. Import models so they register with Base.metadata;
#    then patch any remaining JSONB column types.
# ---------------------------------------------------------------------------
import app.models.models as _models_mod  # noqa: E402
from sqlalchemy import JSON as _JSON  # noqa: E402

for _table in _models_mod.Base.metadata.tables.values():
    for _col in _table.columns:
        if _col.type.__class__.__name__ == "JSONB":
            _col.type = _JSON()

# ---------------------------------------------------------------------------
# 3. Build a SQLite in-memory engine with StaticPool (single shared connection)
#    and swap it into app.db.session before the app is created.
# ---------------------------------------------------------------------------
import app.db.session as _db_session  # noqa: E402
from app.db.base import Base  # noqa: E402

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # all connections share the same in-memory DB
)
Base.metadata.create_all(bind=_TEST_ENGINE)

# Swap the global engine and SessionLocal used by the FastAPI app
_db_session.engine = _TEST_ENGINE
_db_session.SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=_TEST_ENGINE
)

# Patch init_db to a no-op (tables already created above)
_db_session.init_db = lambda: None

# Patch health check to avoid real connection
_db_session.check_db_health = lambda: "healthy"
