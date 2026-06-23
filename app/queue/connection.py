"""
Redis connection and RQ queue management.
"""
from __future__ import annotations

import redis
from rq import Queue

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_redis_conn: redis.Redis | None = None
_queue: Queue | None = None


def get_redis_connection() -> redis.Redis:
    global _redis_conn
    if _redis_conn is None:
        settings = get_settings()
        _redis_conn = redis.from_url(settings.redis_url, decode_responses=False)
    return _redis_conn


def get_queue() -> Queue:
    global _queue
    if _queue is None:
        settings = get_settings()
        conn = get_redis_connection()
        _queue = Queue(
            name=settings.rq_queue_name,
            connection=conn,
            default_timeout=300,
        )
    return _queue


def check_redis_health() -> str:
    """Return 'healthy' or an error string."""
    try:
        conn = get_redis_connection()
        conn.ping()
        return "healthy"
    except Exception as exc:
        return f"unhealthy: {exc}"


def check_worker_health() -> str:
    """Return 'active' if at least one worker is registered, else 'no_workers'."""
    try:
        from rq import Worker
        conn = get_redis_connection()
        workers = Worker.all(connection=conn)
        if workers:
            return f"active ({len(workers)} workers)"
        return "no_workers"
    except Exception as exc:
        return f"unhealthy: {exc}"
