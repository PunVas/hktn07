"""Canonical domain models — provider-agnostic representations.

These are the PORT layer's vocabulary: providers translate their native JSON into
these shapes, so analyzers/scorers/persistence never touch provider-specific formats.
Adding Bitbucket/GitLab = a new provider adapter, not changes here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PRState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class ReviewState(str, Enum):
    PENDING = "pending"
    COMMENTED = "commented"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    DISMISSED = "dismissed"


class CheckStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class PullRequest:
    """Core PR metadata."""
    provider: str
    repo: str
    number: int
    title: str
    description: str
    author: str
    state: PRState
    source_branch: str
    target_branch: str
    commit_sha: str
    base_commit_sha: str
    opened_at: datetime | None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    jira_issue_id: str | None = None
    provider_pr_id: str = ""


@dataclass
class DiffFile:
    """A single changed file in a PR."""
    filename: str
    additions: int
    deletions: int
    status: str  # e.g., "added", "modified", "deleted", "renamed"


@dataclass
class Diff:
    """Aggregated diff stats for a PR."""
    files_changed: int
    additions: int
    deletions: int
    files: list[DiffFile] = field(default_factory=list)


@dataclass
class Review:
    """A review on a PR."""
    reviewer: str
    state: ReviewState
    submitted_at: datetime | None = None


@dataclass
class Check:
    """A CI/CD check/status on a commit."""
    name: str
    status: CheckStatus
    required: bool
    completed_at: datetime | None = None
    url: str | None = None


@dataclass
class Commit:
    """A commit in a PR."""
    sha: str
    author: str
    message: str
    committed_at: datetime | None = None


@dataclass
class PRRef:
    """Lightweight PR reference for listing operations."""
    provider: str
    repo: str
    number: int
    commit_sha: str
    title: str
