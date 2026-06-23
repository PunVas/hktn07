"""
Health check router.
GET /api/health
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db.session import check_db_health
from app.queue.connection import check_redis_health, check_worker_health
from app.schemas.schemas import HealthResponse

router = APIRouter(prefix="", tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    description="Returns health status of database, Redis, and workers.",
)
def health_check() -> HealthResponse:
    db_status = check_db_health()
    redis_status = check_redis_health()
    worker_status = check_worker_health()

    overall = (
        "healthy"
        if db_status == "healthy" and redis_status == "healthy"
        else "degraded"
    )

    return HealthResponse(
        database=db_status,
        redis=redis_status,
        worker=worker_status,
        status=overall,
    )
