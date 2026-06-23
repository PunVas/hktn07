"""
PR Processor Worker.
Contains the job functions executed by RQ workers.
- Idempotent: safe to run multiple times for the same PR.
- Never crashes the worker process on job failure.
- Logs everything with job_id context.
"""
from __future__ import annotations

import time
from typing import Any

from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.services.harness_client import HarnessAPIError, HarnessTransientError, get_harness_client
from app.services.metrics import compute_full_analysis
from app import repository as repo
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_pr_id_from_payload(payload: dict[str, Any]) -> int | None:
    """
    Extract the PR ID from the SCM event metadata.

    Harness SCM webhook payload includes PR number in metadata.
    We support multiple common key names for robustness.
    """
    metadata: dict[str, Any] = payload.get("metadata", {})

    # Try standard Harness webhook keys
    for key in ("pr_number", "pr_id", "number", "pullRequestId", "pull_request_number"):
        value = metadata.get(key)
        if value is not None:
            try:
                return int(value)
            except (ValueError, TypeError):
                continue

    # Fall back to top-level payload keys
    for key in ("pr_number", "pr_id"):
        value = payload.get(key)
        if value is not None:
            try:
                return int(value)
            except (ValueError, TypeError):
                continue

    return None


def _run_pr_analysis(
    job_id: str,
    pr_id: int,
    repository: str,
    provider: str,
) -> None:
    """
    Core analysis pipeline:
    1. Call Harness API for PR details and files.
    2. Compute all metrics.
    3. UPSERT database.
    """
    db = SessionLocal()
    try:
        # Mark job as started
        repo.update_job_status(db, job_id, "started")
        repo.append_processing_log(
            db, job_id, f"Starting analysis for PR #{pr_id}", context={"pr_id": pr_id}
        )
        db.commit()

        start_ts = time.monotonic()

        client = get_harness_client()

        # Fetch PR from Harness
        logger.info("Fetching PR from Harness", extra={"job_id": job_id, "pr_id": pr_id})
        try:
            raw_pr = client.get_pull_request(repo=repository, pr_id=pr_id)
        except HarnessAPIError as exc:
            repo.append_processing_log(
                db, job_id, f"Harness API error: {exc.message}", level="ERROR",
                context={"status_code": exc.status_code}
            )
            repo.update_job_status(db, job_id, "failed", error_message=str(exc))
            db.commit()
            logger.error(
                "Harness API error, job failed",
                extra={"job_id": job_id, "pr_id": pr_id, "error": str(exc)},
            )
            return
        except HarnessTransientError as exc:
            # All retries exhausted
            repo.append_processing_log(
                db, job_id, f"Harness transient error (retries exhausted): {exc}",
                level="ERROR",
            )
            repo.update_job_status(db, job_id, "failed", error_message=str(exc))
            repo.increment_job_retry(db, job_id)
            db.commit()
            logger.error(
                "Harness transient error after retries",
                extra={"job_id": job_id, "pr_id": pr_id},
            )
            return

        # Fetch changed files (best-effort)
        try:
            files = client.get_pull_request_files(repo=repository, pr_id=pr_id)
        except Exception:
            files = []

        # Compute all metrics
        analysis_result = compute_full_analysis(raw_pr=raw_pr, files=files)
        processing_duration_ms = int((time.monotonic() - start_ts) * 1000)

        # UPSERT repository
        db_repo = repo.upsert_repository(db, provider=provider, full_name=repository)

        # UPSERT pull request
        pr_meta = analysis_result["pr_metadata"]
        db_pr = repo.upsert_pull_request(
            db,
            repository_id=db_repo.id,
            pr_id=pr_id,
            title=pr_meta.get("title"),
            author=pr_meta.get("author"),
            state=pr_meta.get("state"),
            source_branch=pr_meta.get("source_branch"),
            target_branch=pr_meta.get("target_branch"),
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

        # Update job link to PR
        repo.update_job_status(db, job_id, "completed", pull_request_id=db_pr.id)
        repo.append_processing_log(
            db,
            job_id,
            f"Analysis complete for PR #{pr_id} in {processing_duration_ms}ms",
            context={
                "pr_id": pr_id,
                "severity_score": analysis_result["severity_score"],
                "processing_duration_ms": processing_duration_ms,
            },
        )
        db.commit()

        logger.info(
            "PR analysis complete",
            extra={
                "job_id": job_id,
                "pr_id": pr_id,
                "severity_score": analysis_result["severity_score"],
                "processing_duration_ms": processing_duration_ms,
            },
        )

    except Exception as exc:
        db.rollback()
        repo.update_job_status(db, job_id, "failed", error_message=str(exc))
        repo.append_processing_log(
            db, job_id, f"Unexpected error: {exc}", level="ERROR",
            context={"error_type": type(exc).__name__}
        )
        db.commit()
        logger.error(
            "Unexpected error in PR analysis",
            extra={"job_id": job_id, "pr_id": pr_id, "error": str(exc)},
            exc_info=True,
        )
    finally:
        db.close()


def process_scm_event(payload: dict[str, Any], job_id: str) -> None:
    """
    RQ job function: process an incoming SCM webhook event.
    Idempotent and never raises to the worker process.
    """
    logger.info("Processing SCM event", extra={"job_id": job_id})

    db = SessionLocal()
    try:
        repo.create_job(
            db,
            job_id=job_id,
            job_type="scm_event",
            payload=payload,
        )
        db.commit()
    except Exception:
        # Job record may already exist from a retry — safe to ignore
        db.rollback()
    finally:
        db.close()

    provider: str = payload.get("provider", "harness")
    repository: str = payload.get("repository", "")
    pr_id = _resolve_pr_id_from_payload(payload)

    if not repository:
        logger.warning("SCM event missing repository", extra={"job_id": job_id})
        db2 = SessionLocal()
        try:
            repo.update_job_status(
                db2, job_id, "failed", error_message="Missing repository in payload"
            )
            db2.commit()
        finally:
            db2.close()
        return

    if pr_id is None:
        logger.warning(
            "SCM event: unable to determine PR ID from payload",
            extra={"job_id": job_id, "payload": payload},
        )
        db2 = SessionLocal()
        try:
            repo.update_job_status(
                db2, job_id, "failed", error_message="Unable to determine PR ID from payload"
            )
            db2.commit()
        finally:
            db2.close()
        return

    _run_pr_analysis(job_id=job_id, pr_id=pr_id, repository=repository, provider=provider)


def process_pr_refresh(
    pr_id: int,
    repository: str,
    provider: str,
    job_id: str,
) -> None:
    """
    RQ job function: refresh analysis for a specific PR.
    Idempotent and never raises to the worker process.
    """
    logger.info("Processing PR refresh", extra={"job_id": job_id, "pr_id": pr_id})

    db = SessionLocal()
    try:
        repo.create_job(
            db,
            job_id=job_id,
            job_type="refresh",
            payload={"pr_id": pr_id, "repository": repository, "provider": provider},
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    _run_pr_analysis(job_id=job_id, pr_id=pr_id, repository=repository, provider=provider)
