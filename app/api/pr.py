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
    response_model=PRDetailResponse,
    status_code=200,
    summary="Refresh PR analysis",
    description=(
        "Analyzes the specified PR and returns the full analysis. "
        "If the PR doesn't exist in the database, provide repository and provider in query params."
    ),
)
def refresh_pr(
    pr_id: int,
    request: Request,
    db: Session = Depends(get_db),
    repository: str | None = None,
    provider: str = "harness",
) -> PRDetailResponse:
    from app.config.settings import get_settings
    from app.providers.registry import get_provider
    from app.services.metrics import compute_full_analysis
    import time

    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info("PR refresh requested", extra={"request_id": request_id, "pr_id": pr_id})

    # Try to find existing PR to get repository and provider info
    existing_pr = repo.get_pull_request_by_pr_id(db, pr_id)

    if existing_pr is None:
        # If no existing PR, repository must be provided as query parameter
        if not repository:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "missing_repository",
                    "message": (
                        f"No record found for PR #{pr_id}. "
                        "Provide 'repository' query parameter (e.g., ?repository=harness-core)."
                    ),
                },
            )
        repository_full_name = repository
        provider_name = provider
        logger.info(
            "First-time PR analysis (no existing record)",
            extra={
                "request_id": request_id,
                "pr_id": pr_id,
                "repository": repository_full_name,
                "provider": provider_name,
            },
        )
    else:
        # Use existing PR's repository and provider
        repository_full_name = existing_pr.repository.full_name
        provider_name = existing_pr.repository.provider

    # Process PR analysis synchronously
    try:
        start_ts = time.monotonic()
        settings = get_settings()

        # Get the appropriate provider
        logger.info(
            "Initializing provider",
            extra={"request_id": request_id, "provider": provider_name, "pr_id": pr_id}
        )
        scm_provider = get_provider(provider_name, settings)

        # Fetch PR from provider
        logger.info(
            "Fetching PR from provider",
            extra={"request_id": request_id, "provider": provider_name, "pr_id": pr_id}
        )
        pr_obj = scm_provider.get_pull_request(repo=repository_full_name, pr_id=pr_id)
        diff = scm_provider.get_diff(repo=repository_full_name, pr_id=pr_id)

        # Compute all metrics from canonical domain models
        analysis_result = compute_full_analysis(pr=pr_obj, diff=diff)
        processing_duration_ms = int((time.monotonic() - start_ts) * 1000)

        # UPSERT repository
        db_repo = repo.upsert_repository(db, provider=provider_name, full_name=repository_full_name)

        # UPSERT pull request
        db_pr = repo.upsert_pull_request(
            db,
            repository_id=db_repo.id,
            pr_id=pr_id,
            title=pr_obj.title,
            author=pr_obj.author,
            state=pr_obj.state.value,
            source_branch=pr_obj.source_branch,
            target_branch=pr_obj.target_branch,
        )

        # UPSERT analysis
        repo.upsert_pr_analysis(
            db,
            pull_request_id=db_pr.id,
            severity_score=analysis_result["severity_score"],
            severity_color=analysis_result["severity_color"],
            dominant_factor=analysis_result["dominant_factor"],
            dominant_factor_icon=analysis_result["dominant_factor_icon"],
            complexity=analysis_result["complexity"],
            files_changed=analysis_result["files_changed"],
            lines_added=analysis_result["lines_added"],
            lines_deleted=analysis_result["lines_deleted"],
            review_time=analysis_result["review_time"],
            blast_radius_score=analysis_result["blast_radius_score"],
            blast_radius_graph=analysis_result["blast_radius_graph"],
            processing_duration_ms=processing_duration_ms,
        )

        db.commit()

        logger.info(
            "PR analysis complete",
            extra={
                "request_id": request_id,
                "pr_id": pr_id,
                "severity_score": analysis_result["severity_score"],
                "processing_duration_ms": processing_duration_ms,
            },
        )

        # Return the full analysis
        detail = get_pr_detail(db, pr_id)
        if detail is None:
            raise HTTPException(status_code=500, detail="Analysis completed but failed to retrieve result")
        return detail

    except Exception as exc:
        db.rollback()
        logger.error(
            "PR analysis failed",
            extra={"request_id": request_id, "pr_id": pr_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "analysis_failed",
                "message": f"Failed to analyze PR: {str(exc)}",
            },
        )
