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
    status_code=200,
    summary="Receive SCM webhook event",
    description=(
        "Accepts a Harness SCM trigger event, validates it, "
        "processes PR analysis synchronously, and returns the result."
    ),
)
def receive_scm_event(
    event: SCMEventRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SCMEventResponse:
    from app.config.settings import get_settings
    from app.providers.registry import get_provider
    from app.services.metrics import compute_full_analysis
    from app.utils.scm_detection import detect_scm_provider, extract_repo_slug_from_url
    import time

    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Detect actual SCM provider from repo_url if provided
    actual_provider = event.provider
    repository_slug = event.repository

    if event.repo_url:
        actual_provider = detect_scm_provider(event.repo_url, fallback_provider=event.provider)
        detected_slug = extract_repo_slug_from_url(event.repo_url)
        if detected_slug:
            repository_slug = detected_slug

    logger.info(
        "SCM event received",
        extra={
            "request_id": request_id,
            "provider": event.provider,
            "actual_provider": actual_provider,
            "event_type": event.event,
            "repository": repository_slug,
            "repo_url": event.repo_url,
            "metadata": event.metadata,
        },
    )

    # Extract PR ID from metadata
    metadata = event.metadata or {}
    pr_id = None

    # Try multiple field names for PR ID
    for key in ("pr_number", "pr_id", "number", "pullRequestId", "pull_request_number"):
        value = metadata.get(key)
        if value is not None:
            try:
                pr_id = int(value)
                break
            except (ValueError, TypeError):
                continue

    if pr_id is None:
        logger.warning(
            "Unable to determine PR ID from payload",
            extra={"request_id": request_id, "metadata": metadata}
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_pr_id",
                "message": (
                    "Unable to determine PR ID from payload. "
                    "Expected 'pr_number', 'pr_id', or 'number' in metadata."
                ),
            },
        )

    repository = repository_slug
    provider = actual_provider

    logger.info(
        "Processing PR from SCM event",
        extra={
            "request_id": request_id,
            "pr_id": pr_id,
            "repository": repository,
            "provider": provider,
        }
    )

    # Process PR analysis synchronously (same as refresh endpoint)
    try:
        start_ts = time.monotonic()
        settings = get_settings()

        # Get the appropriate provider
        scm_provider = get_provider(provider, settings)

        # Fetch PR from provider
        pr_obj = scm_provider.get_pull_request(repo=repository, pr_id=pr_id)
        diff = scm_provider.get_diff(repo=repository, pr_id=pr_id)

        # Compute all metrics
        analysis_result = compute_full_analysis(pr=pr_obj, diff=diff)
        processing_duration_ms = int((time.monotonic() - start_ts) * 1000)

        # UPSERT repository
        db_repo = repo.upsert_repository(db, provider=provider, full_name=repository)

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
            criticality=analysis_result["criticality"],
            estimated_review_time=analysis_result["estimated_review_time"],
            reviewers_needed=analysis_result["reviewers_needed"],
            processing_duration_ms=processing_duration_ms,
        )

        db.commit()

        logger.info(
            "SCM event processed successfully",
            extra={
                "request_id": request_id,
                "pr_id": pr_id,
                "severity_score": analysis_result["severity_score"],
                "processing_duration_ms": processing_duration_ms,
            },
        )

        return SCMEventResponse(
            status="completed",
            job_id=request_id,
            message=f"PR #{pr_id} analyzed successfully. Severity: {analysis_result['severity_score']}",
        )

    except Exception as exc:
        db.rollback()
        logger.error(
            "SCM event processing failed",
            extra={"request_id": request_id, "pr_id": pr_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "processing_failed",
                "message": f"Failed to process SCM event: {str(exc)}",
            },
        )
