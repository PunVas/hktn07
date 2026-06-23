"""
Job enqueue helpers.
All jobs are enqueued here — a single place to control retry and timeout policies.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.queue.connection import get_queue
from app.utils.logging import get_logger

logger = get_logger(__name__)

_JOB_TIMEOUT = 300  # seconds
_TTL = 3600  # result TTL


def enqueue_scm_event(payload: dict[str, Any]) -> str:
    """
    Enqueue an SCM event processing job.
    Returns the job_id string.
    """
    from app.workers.pr_processor import process_scm_event  # local import avoids circular deps

    job_id = str(uuid.uuid4())
    queue = get_queue()

    queue.enqueue(
        process_scm_event,
        kwargs={"payload": payload, "job_id": job_id},
        job_id=job_id,
        job_timeout=_JOB_TIMEOUT,
        result_ttl=_TTL,
        failure_ttl=_TTL,
    )

    logger.info("SCM event enqueued", extra={"job_id": job_id, "payload": payload})
    return job_id


def enqueue_pr_refresh(pr_id: int, repository: str, provider: str) -> str:
    """
    Enqueue a PR refresh job.
    Returns the job_id string.
    """
    from app.workers.pr_processor import process_pr_refresh

    job_id = str(uuid.uuid4())
    queue = get_queue()

    queue.enqueue(
        process_pr_refresh,
        kwargs={
            "pr_id": pr_id,
            "repository": repository,
            "provider": provider,
            "job_id": job_id,
        },
        job_id=job_id,
        job_timeout=_JOB_TIMEOUT,
        result_ttl=_TTL,
        failure_ttl=_TTL,
    )

    logger.info("PR refresh enqueued", extra={"job_id": job_id, "pr_id": pr_id})
    return job_id
