"""
Repository layer: all database access for PR Guardian.
Business logic lives in services; this layer only touches the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.models import Job, PRAnalysis, ProcessingLog, PullRequest, Repository
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

def upsert_repository(db: Session, provider: str, full_name: str) -> Repository:
    """Return existing or create new repository record."""
    stmt = select(Repository).where(Repository.full_name == full_name)
    repo = db.execute(stmt).scalar_one_or_none()
    if repo is None:
        repo = Repository(provider=provider, full_name=full_name)
        db.add(repo)
        db.flush()
        logger.info("Created repository", extra={"full_name": full_name})
    return repo


def get_repository_by_name(db: Session, full_name: str) -> Repository | None:
    stmt = select(Repository).where(Repository.full_name == full_name)
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Pull Requests
# ---------------------------------------------------------------------------

def upsert_pull_request(
    db: Session,
    repository_id: int,
    pr_id: int,
    title: str | None = None,
    author: str | None = None,
    state: str | None = None,
    source_branch: str | None = None,
    target_branch: str | None = None,
) -> PullRequest:
    """Create or update a pull request record."""
    stmt = select(PullRequest).where(
        PullRequest.repository_id == repository_id,
        PullRequest.pr_id == pr_id,
    )
    pr = db.execute(stmt).scalar_one_or_none()
    if pr is None:
        pr = PullRequest(
            repository_id=repository_id,
            pr_id=pr_id,
            title=title,
            author=author,
            state=state,
            source_branch=source_branch,
            target_branch=target_branch,
        )
        db.add(pr)
        db.flush()
        logger.info("Created pull request", extra={"pr_id": pr_id})
    else:
        if title is not None:
            pr.title = title
        if author is not None:
            pr.author = author
        if state is not None:
            pr.state = state
        if source_branch is not None:
            pr.source_branch = source_branch
        if target_branch is not None:
            pr.target_branch = target_branch
        db.flush()
    return pr


def get_pull_request_by_pr_id(db: Session, pr_id: int) -> PullRequest | None:
    """Fetch a pull request by its external PR ID (not DB primary key)."""
    stmt = select(PullRequest).where(PullRequest.pr_id == pr_id)
    return db.execute(stmt).scalar_one_or_none()


def get_pull_requests_by_pr_ids(db: Session, pr_ids: list[int]) -> list[PullRequest]:
    stmt = select(PullRequest).where(PullRequest.pr_id.in_(pr_ids))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# PR Analysis
# ---------------------------------------------------------------------------

def upsert_pr_analysis(
    db: Session,
    pull_request_id: int,
    severity_score: int,
    severity_color: str,
    dominant_factor: str | None,
    dominant_factor_icon: str | None,
    complexity: int,
    files_changed: int,
    lines_added: int,
    lines_deleted: int,
    review_time: int,
    blast_radius_score: int,
    blast_radius_graph: dict[str, Any],
    criticality: int = 0,
    estimated_review_time: int = 0,
    reviewers_needed: int = 0,
    processing_duration_ms: int | None = None,
) -> PRAnalysis:
    """Create or update a PR analysis record."""
    stmt = select(PRAnalysis).where(PRAnalysis.pull_request_id == pull_request_id)
    analysis = db.execute(stmt).scalar_one_or_none()

    now = datetime.now(tz=timezone.utc)

    if analysis is None:
        analysis = PRAnalysis(
            pull_request_id=pull_request_id,
            severity_score=severity_score,
            severity_color=severity_color,
            dominant_factor=dominant_factor,
            dominant_factor_icon=dominant_factor_icon,
            complexity=complexity,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_deleted=lines_deleted,
            review_time=review_time,
            blast_radius_score=blast_radius_score,
            blast_radius_graph=blast_radius_graph,
            criticality=criticality,
            estimated_review_time=estimated_review_time,
            reviewers_needed=reviewers_needed,
            last_updated=now,
            processing_duration_ms=processing_duration_ms,
        )
        db.add(analysis)
        db.flush()
    else:
        analysis.severity_score = severity_score
        analysis.severity_color = severity_color
        analysis.dominant_factor = dominant_factor
        analysis.dominant_factor_icon = dominant_factor_icon
        analysis.complexity = complexity
        analysis.files_changed = files_changed
        analysis.lines_added = lines_added
        analysis.lines_deleted = lines_deleted
        analysis.review_time = review_time
        analysis.blast_radius_score = blast_radius_score
        analysis.blast_radius_graph = blast_radius_graph
        analysis.criticality = criticality
        analysis.estimated_review_time = estimated_review_time
        analysis.reviewers_needed = reviewers_needed
        analysis.last_updated = now
        analysis.processing_duration_ms = processing_duration_ms
        db.flush()

    return analysis


def get_analysis_for_pr(db: Session, pull_request_id: int) -> PRAnalysis | None:
    stmt = select(PRAnalysis).where(PRAnalysis.pull_request_id == pull_request_id)
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def create_job(
    db: Session,
    job_id: str,
    job_type: str,
    payload: dict[str, Any] | None = None,
    pull_request_id: int | None = None,
) -> Job:
    job = Job(
        job_id=job_id,
        job_type=job_type,
        status="queued",
        payload=payload,
        pull_request_id=pull_request_id,
    )
    db.add(job)
    db.flush()
    return job


def update_job_status(
    db: Session,
    job_id: str,
    status: str,
    error_message: str | None = None,
    pull_request_id: int | None = None,
) -> None:
    stmt = select(Job).where(Job.job_id == job_id)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return
    job.status = status
    if error_message is not None:
        job.error_message = error_message
    if pull_request_id is not None:
        job.pull_request_id = pull_request_id
    job.updated_at = datetime.now(tz=timezone.utc)
    db.flush()


def increment_job_retry(db: Session, job_id: str) -> None:
    stmt = select(Job).where(Job.job_id == job_id)
    job = db.execute(stmt).scalar_one_or_none()
    if job:
        job.retry_count += 1
        db.flush()


def get_job(db: Session, job_id: str) -> Job | None:
    stmt = select(Job).where(Job.job_id == job_id)
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Processing Logs
# ---------------------------------------------------------------------------

def append_processing_log(
    db: Session,
    job_id: str,
    message: str,
    level: str = "INFO",
    context: dict[str, Any] | None = None,
) -> None:
    log = ProcessingLog(job_id=job_id, level=level, message=message, context=context)
    db.add(log)
    db.flush()
