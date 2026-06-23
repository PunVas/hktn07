"""
ORM models for PR Guardian.
Tables are created automatically via Base.metadata.create_all().
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------

class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pull_requests: Mapped[list[PullRequest]] = relationship(
        "PullRequest", back_populates="repository", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_repositories_full_name", "full_name"),)


# ---------------------------------------------------------------------------
# pull_requests
# ---------------------------------------------------------------------------

class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    pr_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_branch: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_branch: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    repository: Mapped[Repository] = relationship("Repository", back_populates="pull_requests")
    analysis: Mapped[PRAnalysis | None] = relationship(
        "PRAnalysis", back_populates="pull_request", uselist=False, cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(
        "Job", back_populates="pull_request", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "pr_id", name="uq_pull_requests_repo_pr"),
        Index("ix_pull_requests_pr_id", "pr_id"),
        Index("ix_pull_requests_repository_id", "repository_id"),
    )


# ---------------------------------------------------------------------------
# pr_analysis
# ---------------------------------------------------------------------------

class PRAnalysis(Base):
    __tablename__ = "pr_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pull_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Severity
    severity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_color: Mapped[str] = mapped_column(String(16), nullable=False, default="green")
    dominant_factor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dominant_factor_icon: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Metrics
    complexity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blast_radius_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criticality: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_review_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewers_needed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Blast radius graph (JSON)
    blast_radius_graph: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processing_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    pull_request: Mapped[PullRequest] = relationship("PullRequest", back_populates="analysis")

    __table_args__ = (Index("ix_pr_analysis_pull_request_id", "pull_request_id"),)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    pull_request_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "scm_event" | "refresh"
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued"
    )  # queued | started | completed | failed
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pull_request: Mapped[PullRequest | None] = relationship("PullRequest", back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_job_id", "job_id"),
        Index("ix_jobs_status", "status"),
    )


# ---------------------------------------------------------------------------
# processing_logs
# ---------------------------------------------------------------------------

class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_processing_logs_job_id", "job_id"),)
