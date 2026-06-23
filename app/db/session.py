"""
SQLAlchemy engine and session factory.
Tables are created automatically on startup — no Alembic.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not exist. Called at application startup."""
    from app.db.base import Base  # noqa: F401 – triggers model registration
    import app.models  # noqa: F401

    logger.info("Initializing database schema")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ready")


def check_db_health() -> str:
    """Return 'healthy' or an error string."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "healthy"
    except Exception as exc:
        return f"unhealthy: {exc}"
