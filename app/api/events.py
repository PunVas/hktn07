"""
SCM Events API router.
POST /api/events/scm
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app import repository as repo
from app.queue.enqueue import enqueue_scm_event
from app.schemas.schemas import SCMEventRequest, SCMEventResponse
from app.utils.logging import get_logger

router = APIRouter(prefix="/events", tags=["events"])
logger = get_logger(__name__)


@router.post(
    "/scm",
    response_model=SCMEventResponse,
    status_code=202,
    summary="Receive SCM webhook event",
    description=(
        "Accepts a Harness SCM trigger event, validates it, "
        "enqueues it for async processing, and returns HTTP 202 immediately."
    ),
)
def receive_scm_event(
    event: SCMEventRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SCMEventResponse:
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        "SCM event received",
        extra={
            "request_id": request_id,
            "provider": event.provider,
            "event_type": event.event,
            "repository": event.repository,
        },
    )

    payload = event.model_dump()
    job_id = enqueue_scm_event(payload)

    logger.info("SCM event queued", extra={"request_id": request_id, "job_id": job_id})
    return SCMEventResponse(status="queued", job_id=job_id)
