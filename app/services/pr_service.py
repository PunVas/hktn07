"""
PR service: orchestrates DB reads to serve the API layer.
Never calls external APIs. Only reads from the database.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import repository as repo
from app.models.models import PRAnalysis, PullRequest
from app.schemas.schemas import (
    BlastRadiusGraph,
    PRDetailResponse,
    PRMetrics,
    PRSummary,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

_EMPTY_BLAST_RADIUS: dict[str, Any] = {
    "center": {},
    "ring_nodes": [],
    "outer_nodes": [],
    "edges": [],
}


def get_pr_summary_list(db: Session, pr_ids: list[int]) -> list[PRSummary]:
    """
    Return summary info for the given pr_ids, served from DB cache only.
    PRs without analysis are returned with zero scores.
    """
    pull_requests = repo.get_pull_requests_by_pr_ids(db, pr_ids)
    pr_map: dict[int, PullRequest] = {pr.pr_id: pr for pr in pull_requests}

    summaries: list[PRSummary] = []
    for pr_id in pr_ids:
        pr = pr_map.get(pr_id)
        if pr is None or pr.analysis is None:
            summaries.append(
                PRSummary(
                    pr_id=pr_id,
                    severity_score=0,
                    severity_color="unknown",
                    dominant_factor=None,
                    dominant_factor_icon=None,
                )
            )
        else:
            analysis: PRAnalysis = pr.analysis
            summaries.append(
                PRSummary(
                    pr_id=pr_id,
                    severity_score=analysis.severity_score,
                    severity_color=analysis.severity_color,
                    dominant_factor=analysis.dominant_factor,
                    dominant_factor_icon=analysis.dominant_factor_icon,
                )
            )
    return summaries


def get_pr_detail(db: Session, pr_id: int) -> PRDetailResponse | None:
    """
    Return full PR detail served from DB cache only.
    Returns None if the PR has not been analysed yet.
    """
    pr = repo.get_pull_request_by_pr_id(db, pr_id)
    if pr is None or pr.analysis is None:
        return None

    analysis: PRAnalysis = pr.analysis
    graph_data: dict[str, Any] = analysis.blast_radius_graph or _EMPTY_BLAST_RADIUS

    return PRDetailResponse(
        pr_id=pr_id,
        severity_score=analysis.severity_score,
        dominant_factor=analysis.dominant_factor,
        metrics=PRMetrics(
            complexity=analysis.complexity,
            files_changed=analysis.files_changed,
            lines_added=analysis.lines_added,
            lines_deleted=analysis.lines_deleted,
            review_time=analysis.review_time,
            blast_radius_score=analysis.blast_radius_score,
            criticality=analysis.criticality,
            estimated_review_time=analysis.estimated_review_time,
            reviewers_needed=analysis.reviewers_needed,
        ),
        blast_radius=BlastRadiusGraph(
            center=graph_data.get("center", {}),
            ring_nodes=graph_data.get("ring_nodes", []),
            outer_nodes=graph_data.get("outer_nodes", []),
            edges=graph_data.get("edges", []),
        ),
        last_updated=analysis.last_updated,
    )
