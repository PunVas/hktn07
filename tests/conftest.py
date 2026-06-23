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
# 1. Import models so they register with Base.metadata
# ---------------------------------------------------------------------------
import app.models.models as _models_mod  # noqa: E402

# ---------------------------------------------------------------------------
# 2. Build a SQLite in-memory engine with StaticPool (single shared connection)
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
