"""
Pydantic v2 schemas for all API request/response contracts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# SCM Events
# ---------------------------------------------------------------------------

class SCMEventRequest(BaseModel):
    provider: str = Field(..., description="SCM provider name, e.g. 'harness'")
    event: str = Field(..., description="Event type, e.g. 'pr.opened'")
    repository: str = Field(..., description="Full repository name, e.g. 'org/repo'")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SCMEventResponse(BaseModel):
    status: str = "queued"
    job_id: str


# ---------------------------------------------------------------------------
# PR List
# ---------------------------------------------------------------------------

class PRListRequest(BaseModel):
    pr_ids: list[int] = Field(..., min_length=1)


class PRSummary(BaseModel):
    pr_id: int
    severity_score: int
    severity_color: str
    dominant_factor: str | None
    dominant_factor_icon: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# PR Detail
# ---------------------------------------------------------------------------

class PRMetrics(BaseModel):
    complexity: int
    files_changed: int
    lines_added: int
    lines_deleted: int
    review_time: int
    blast_radius_score: int

    model_config = {"from_attributes": True}


class BlastRadiusNode(BaseModel):
    id: str
    label: str
    type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlastRadiusEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str | None = None


class BlastRadiusGraph(BaseModel):
    center: dict[str, Any]
    ring_nodes: list[dict[str, Any]]
    outer_nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class PRDetailResponse(BaseModel):
    pr_id: int
    severity_score: int
    dominant_factor: str | None
    metrics: PRMetrics
    blast_radius: BlastRadiusGraph
    last_updated: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

class RefreshResponse(BaseModel):
    status: str = "queued"
    job_id: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    database: str
    redis: str
    worker: str
    status: str


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class JobStatus(BaseModel):
    job_id: str
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
