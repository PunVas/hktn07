"""
PR API router.

POST /api/pr/list       — summary list (served from DB cache)
GET  /api/pr/{pr_id}    — full detail (served from DB cache)
POST /api/pr/{pr_id}/refresh — enqueue refresh job
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app import repository as repo
from app.queue.enqueue import enqueue_pr_refresh
from app.schemas.schemas import (
    PRDetailResponse,
    PRListRequest,
    PRSummary,
    RefreshResponse,
)
from app.services.pr_service import get_pr_detail, get_pr_summary_list
from app.utils.logging import get_logger

router = APIRouter(prefix="/pr", tags=["pr"])
logger = get_logger(__name__)


@router.post(
    "/list",
    response_model=list[PRSummary],
    summary="Get PR summary list",
    description=(
        "Returns severity summary for multiple PRs. "
        "Served exclusively from the database cache — no external API calls."
    ),
)
def list_prs(
    body: PRListRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> list[PRSummary]:
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        "PR list requested",
        extra={"request_id": request_id, "pr_count": len(body.pr_ids)},
    )
    return get_pr_summary_list(db, body.pr_ids)


@router.get(
    "/{pr_id}",
    response_model=PRDetailResponse,
    summary="Get PR detail",
    description=(
        "Returns full PR analysis for the floating insights panel. "
        "Served exclusively from the database cache — no external API calls."
    ),
)
def get_pr(
    pr_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> PRDetailResponse:
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info("PR detail requested", extra={"request_id": request_id, "pr_id": pr_id})

    detail = get_pr_detail(db, pr_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": (
                    f"PR #{pr_id} has not been analysed yet. "
                    "Trigger analysis via POST /api/pr/{pr_id}/refresh."
                ),
            },
        )
    return detail


@router.post(
    "/{pr_id}/refresh",
    response_model=RefreshResponse,
    status_code=202,
    summary="Refresh PR analysis",
    description="Enqueues a re-analysis job for the specified PR.",
)
def refresh_pr(
    pr_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info("PR refresh requested", extra={"request_id": request_id, "pr_id": pr_id})

    # Try to find existing PR to get repository and provider info
    existing_pr = repo.get_pull_request_by_pr_id(db, pr_id)
    if existing_pr is None:
        # Cannot refresh a PR we have no record of. Client must send an SCM event first.
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": (
                    f"No record found for PR #{pr_id}. "
                    "Send a POST /api/events/scm event first."
                ),
            },
        )

    repository_full_name: str = existing_pr.repository.full_name
    provider: str = existing_pr.repository.provider

    job_id = enqueue_pr_refresh(
        pr_id=pr_id,
        repository=repository_full_name,
        provider=provider,
    )

    logger.info("PR refresh enqueued", extra={"request_id": request_id, "job_id": job_id})
    return RefreshResponse(status="queued", job_id=job_id)
