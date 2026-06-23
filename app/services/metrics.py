"""
Metrics computation engine for PR Guardian.
Takes raw Harness PR data and computes all required metrics.
Pure functions — no side effects, fully testable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.diff_parser import FileDiffSummary, parse_pr_files
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Max values used for normalisation (adjust based on real PRs)
MAX_FILES = 100
MAX_BLAST_RADIUS = 20


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, value)))


def _normalise(value: float, maximum: float) -> float:
    """Return 0–1 normalised ratio."""
    if maximum <= 0:
        return 0.0
    return min(value / maximum, 1.0)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Metrics extraction
# ---------------------------------------------------------------------------

def extract_pr_metadata(
    raw: dict[str, Any],
    reviewers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Extract normalised fields from the Harness PR API response.

    Harness PR response shape (relevant fields):
    {
        "number": 119080,
        "title": "...",
        "author": {"display_name": "...", "uid": "..."},
        "state": "open",
        "source_branch": "feature/...",
        "target_branch": "main",
        "created": "2024-01-01T00:00:00Z",
        "updated": "2024-01-01T01:00:00Z",
        "merge_base_sha": "...",
        "stats": {
            "conversations": 3,
            "unresolved_count": 1,
            "commits": 5,
            "files_changed": 31,
            "additions": 1231,
            "deletions": 438,
        }
    }
    """
    stats: dict[str, Any] = raw.get("stats", {})
    author_obj = raw.get("author", {})
    author_name: str = author_obj.get("display_name") or author_obj.get("uid", "unknown")

    files_changed: int = stats.get("files_changed", 0)
    lines_added: int = stats.get("additions", 0)
    lines_deleted: int = stats.get("deletions", 0)
    commits: int = stats.get("commits", 0)

    created = _parse_iso(raw.get("created"))
    updated = _parse_iso(raw.get("updated"))

    review_time_hours = 0
    if created and updated and updated > created:
        delta = updated - created
        review_time_hours = int(delta.total_seconds() / 3600)

    # PR age = time since the PR was opened (hours).
    pr_age_hours = 0
    if created:
        delta = datetime.now(timezone.utc) - created
        pr_age_hours = max(int(delta.total_seconds() / 3600), 0)

    # Current number of reviewers — the "list reviewers" response is an array
    # of reviewer objects, so the count is simply its length.
    reviewers_count = len(reviewers) if isinstance(reviewers, list) else 0

    return {
        "pr_id": raw.get("number", 0),
        "title": raw.get("title", ""),
        "author": author_name,
        "state": raw.get("state", "unknown"),
        "source_branch": raw.get("source_branch", ""),
        "target_branch": raw.get("target_branch", ""),
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "commits": commits,
        "review_time": review_time_hours,
        "pr_age_hours": pr_age_hours,
        "reviewers_count": reviewers_count,
    }


# ---------------------------------------------------------------------------
# Blast Radius computation (function-level)
# ---------------------------------------------------------------------------

# Change type → color hint for the frontend
_CHANGE_TYPE_COLOR: dict[str, str] = {
    "added": "green",
    "modified": "amber",
    "deleted": "red",
}


def compute_blast_radius(
    files: list[dict[str, Any]],
    pr_metadata: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """
    Build a function-level blast radius graph and compute a blast radius score.

    Graph hierarchy:
        center  → PR itself
        ring_nodes  → changed functions/methods (parsed from diff)
        outer_nodes → affected functions (mocked for demo)
        edges   → PR→changed_fn and changed_fn→affected_fn

    If the Harness API returned diff patch content, we parse it to show
    exactly which functions were added / modified / deleted.
    Falls back to a generic changes node if no patch data is available.

    Returns:
        (graph_dict, blast_radius_score)
    """
    pr_id = pr_metadata["pr_id"]
    center_id = f"pr-{pr_id}"

    # Parse diff content for function-level detail
    file_summaries: list[FileDiffSummary] = parse_pr_files(files)

    # Fall back to synthesized file list if the API returned nothing
    if not file_summaries and pr_metadata["files_changed"] > 0:
        file_summaries = [
            FileDiffSummary(
                path=f"unknown/file_{i}",
                language="Unknown",
                additions=0,
                deletions=0,
                functions=[],
            )
            for i in range(min(pr_metadata["files_changed"], 20))
        ]

    center: dict[str, Any] = {
        "id": center_id,
        "label": f"PR #{pr_id}",
        "type": "pr",
        "metadata": {
            "title": pr_metadata.get("title", ""),
            "author": pr_metadata.get("author", ""),
            "files_changed": pr_metadata["files_changed"],
            "lines_added": pr_metadata["lines_added"],
            "lines_deleted": pr_metadata["lines_deleted"],
        },
    }

    ring_nodes: list[dict[str, Any]] = []
    outer_nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    total_functions_changed = 0

    import random

    for summary in file_summaries:
        safe_path = summary.path.replace("/", "-").replace(".", "_")

        if summary.functions:
            total_functions_changed += len(summary.functions)
            for func in summary.functions:
                func_id = f"fn-{safe_path}-{func.name}"
                
                # Add changed function to INNER RING
                ring_nodes.append(
                    {
                        "id": func_id,
                        "label": f"{func.name}()",
                        "type": "function",
                        "metadata": {
                            "change_type": func.change_type,
                            "change_color": _CHANGE_TYPE_COLOR.get(func.change_type, "gray"),
                            "language": func.language,
                            "line_number": func.line_number,
                            "file": summary.path,
                        },
                    }
                )
                edges.append(
                    {
                        "id": f"e-{center_id}-{func_id}",
                        "source": center_id,
                        "target": func_id,
                        "label": None,
                    }
                )
                
                # Add mock affected functions to OUTER RING
                random.seed(func_id)  # deterministic for same function
                num_affected = random.randint(1, 3)
                mock_names = ["process_data", "handle_request", "update_state", "render_view", "sync_db", "notify_user", "api_gateway", "middleware_check"]
                
                for i in range(num_affected):
                    affected_id = f"af-{func_id}-{i}"
                    affected_label = f"{random.choice(mock_names)}()"
                    
                    outer_nodes.append(
                        {
                            "id": affected_id,
                            "label": affected_label,
                            "type": "affected_function",
                            "metadata": {
                                "change_type": "none",
                                "change_color": "purple", 
                            },
                        }
                    )
                    edges.append(
                        {
                            "id": f"e-{func_id}-{affected_id}",
                            "source": func_id,
                            "target": affected_id,
                            "label": "affects",
                        }
                    )
        else:
            # No function data — add a generic "changes" placeholder node
            placeholder_id = f"fn-{safe_path}-changes"
            ring_nodes.append(
                {
                    "id": placeholder_id,
                    "label": f"changes in {summary.path.rsplit('/', 1)[-1]}",
                    "type": "function",
                    "metadata": {
                        "change_type": "modified",
                        "change_color": "amber",
                        "language": summary.language,
                        "line_number": None,
                        "file": summary.path,
                    },
                }
            )
            edges.append(
                {
                    "id": f"e-{center_id}-{placeholder_id}",
                    "source": center_id,
                    "target": placeholder_id,
                    "label": None,
                }
            )
            
            # Add mock affected functions
            random.seed(placeholder_id)
            num_affected = random.randint(1, 2)
            mock_names = ["core_module", "system_init", "cache_manager"]
            
            for i in range(num_affected):
                affected_id = f"af-{placeholder_id}-{i}"
                affected_label = f"{random.choice(mock_names)}()"
                
                outer_nodes.append(
                    {
                        "id": affected_id,
                        "label": affected_label,
                        "type": "affected_function",
                        "metadata": {
                            "change_type": "none",
                            "change_color": "purple", 
                        },
                    }
                )
                edges.append(
                    {
                        "id": f"e-{placeholder_id}-{affected_id}",
                        "source": placeholder_id,
                        "target": affected_id,
                        "label": "affects",
                    }
                )

    # Blast radius score: weighted by files + distinct functions changed
    num_files = len(file_summaries)
    raw_score = (
        _normalise(num_files, MAX_FILES) * 50
        + _normalise(total_functions_changed, MAX_BLAST_RADIUS * 3) * 50
    )
    blast_radius_score = _clamp(raw_score)

    graph: dict[str, Any] = {
        "center": center,
        "ring_nodes": ring_nodes,
        "outer_nodes": outer_nodes,
        "edges": edges,
    }

    return graph, blast_radius_score


# ---------------------------------------------------------------------------
# Criticality score
# ---------------------------------------------------------------------------

def compute_criticality(
    lines_changed: int,
    files_changed: int,
    pr_age_hours: int,
) -> int:
    """
    Criticality score (0–100).

    Params:
        lines_changed: total LoC changed (additions + deletions)
        files_changed: number of files changed in the PR
        pr_age_hours:  age of the PR in hours (time since it was opened)

    TODO: replace with the mathematical model once provided.
    """
    # Placeholder until the mathematical model is supplied.
    return 0


# ---------------------------------------------------------------------------
# Review time estimate
# ---------------------------------------------------------------------------

def compute_review_time(
    lines_changed: int,
    reviewers_count: int,
) -> int:
    """
    Estimated review time (0–100, or hours — TBD by model).

    Params:
        lines_changed:   total LoC changed (additions + deletions)
        reviewers_count: current number of reviewers on the PR

    TODO: replace with the mathematical model once provided.
    """
    # Placeholder until the mathematical model is supplied.
    return 0


# ---------------------------------------------------------------------------
# Reviewers needed
# ---------------------------------------------------------------------------

def compute_reviewer_needed(
    lines_changed: int,
    file_type_count: int,
) -> int:
    """
    Recommended number of reviewers.

    Params:
        lines_changed:   total LoC changed (additions + deletions)
        file_type_count: number of different file types touched

    TODO: replace with the mathematical model once provided.
    """
    # Placeholder until the mathematical model is supplied.
    return 0


# ---------------------------------------------------------------------------
# Full analysis pipeline
# ---------------------------------------------------------------------------

def compute_full_analysis(
    raw_pr: dict[str, Any],
    files: list[dict[str, Any]],
    reviewers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Orchestrate the complete metric computation pipeline.

    Args:
        raw_pr:    Raw Harness PR API response dict.
        files:     List of file diff dicts from the files endpoint.
                   Each entry may contain a `patch` field with unified diff text
                   for function-level blast radius analysis.
        reviewers: "list reviewers" response — an array of reviewer objects;
                   its length is used as the current reviewer count.

    Returns:
        Dict ready for upsert_pr_analysis().
    """
    metadata = extract_pr_metadata(raw_pr, reviewers)

    blast_radius_graph, blast_radius_score = compute_blast_radius(files, metadata)

    lines_changed = metadata["lines_added"] + metadata["lines_deleted"]

    # Number of different file types touched (distinct languages from the diff).
    file_summaries: list[FileDiffSummary] = parse_pr_files(files)
    file_type_count = len({s.language for s in file_summaries})

    criticality = compute_criticality(
        lines_changed=lines_changed,
        files_changed=metadata["files_changed"],
        pr_age_hours=metadata["pr_age_hours"],
    )

    review_time = compute_review_time(
        lines_changed=lines_changed,
        reviewers_count=metadata["reviewers_count"],
    )

    reviewer_needed = compute_reviewer_needed(
        lines_changed=lines_changed,
        file_type_count=file_type_count,
    )

    logger.info(
        "Analysis computed",
        extra={
            "pr_id": metadata["pr_id"],
            "criticality": criticality,
            "review_time": review_time,
            "reviewer_needed": reviewer_needed,
            "blast_radius_score": blast_radius_score,
        },
    )

    return {
        "pr_metadata": metadata,
        "criticality": criticality,
        "review_time": review_time,
        "reviewer_needed": reviewer_needed,
        "files_changed": metadata["files_changed"],
        "lines_added": metadata["lines_added"],
        "lines_deleted": metadata["lines_deleted"],
        "blast_radius_score": blast_radius_score,
        "blast_radius_graph": blast_radius_graph,
    }
