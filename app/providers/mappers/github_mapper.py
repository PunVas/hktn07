"""GitHub REST v3 JSON -> canonical domain models.

PURE mapping functions (no network). The GitHubProvider fetches raw JSON and
hands it here; tests feed captured fixtures directly. All GitHub-specific field
names and quirks are contained in this module.
"""
from __future__ import annotations

from datetime import datetime

from app.analyzers.ticket_linkage import extract_jira_key
from app.domain.models import (
    Check,
    CheckStatus,
    Commit,
    Diff,
    DiffFile,
    PRRef,
    PullRequest,
    PRState,
    Review,
    ReviewState,
)

PROVIDER = "github"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # GitHub uses RFC3339 "2011-01-26T19:01:12Z"; fromisoformat handles 'Z' on 3.11+.
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _pr_state(pr: dict) -> PRState:
    if pr.get("merged_at") or pr.get("merged"):
        return PRState.MERGED
    if pr.get("state") == "closed":
        return PRState.CLOSED
    return PRState.OPEN


def map_pull_request(pr: dict, repo: str) -> PullRequest:
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    source_branch = head.get("ref", "")
    jira = extract_jira_key(title, body, source_branch)
    return PullRequest(
        provider=PROVIDER,
        repo=repo,
        number=int(pr["number"]),
        title=title,
        description=body,
        author=(pr.get("user") or {}).get("login") or "unknown",
        state=_pr_state(pr),
        source_branch=source_branch,
        target_branch=base.get("ref", ""),
        commit_sha=head.get("sha", ""),
        base_commit_sha=base.get("sha", ""),
        opened_at=_dt(pr.get("created_at")),
        merged_at=_dt(pr.get("merged_at")),
        closed_at=_dt(pr.get("closed_at")),
        jira_issue_id=jira,
        provider_pr_id=str(pr["number"]),
    )


def map_diff(files: list[dict], pr: dict | None = None) -> Diff:
    diff_files = [
        DiffFile(
            filename=f.get("filename", ""),
            additions=int(f.get("additions", 0)),
            deletions=int(f.get("deletions", 0)),
            status=f.get("status", "modified"),
        )
        for f in files
    ]
    # Prefer authoritative PR totals when available; else sum the file rows.
    additions = int((pr or {}).get("additions", sum(f.additions for f in diff_files)))
    deletions = int((pr or {}).get("deletions", sum(f.deletions for f in diff_files)))
    files_changed = int((pr or {}).get("changed_files", len(diff_files)))
    return Diff(
        files_changed=files_changed,
        additions=additions,
        deletions=deletions,
        files=diff_files,
    )


_REVIEW_STATE = {
    "APPROVED": ReviewState.APPROVED,
    "CHANGES_REQUESTED": ReviewState.CHANGES_REQUESTED,
    "COMMENTED": ReviewState.COMMENTED,
    "DISMISSED": ReviewState.DISMISSED,
    "PENDING": ReviewState.PENDING,
}


def map_reviews(reviews: list[dict]) -> list[Review]:
    out: list[Review] = []
    for r in reviews:
        out.append(
            Review(
                reviewer=(r.get("user") or {}).get("login") or "unknown",
                state=_REVIEW_STATE.get((r.get("state") or "").upper(), ReviewState.COMMENTED),
                submitted_at=_dt(r.get("submitted_at")),
                lines_commented=0,
            )
        )
    return out


def _check_status(run: dict) -> CheckStatus:
    if run.get("status") != "completed":
        return CheckStatus.PENDING
    conclusion = (run.get("conclusion") or "").lower()
    return {
        "success": CheckStatus.SUCCESS,
        "failure": CheckStatus.FAILURE,
        "timed_out": CheckStatus.FAILURE,
        "action_required": CheckStatus.FAILURE,
        "cancelled": CheckStatus.FAILURE,
        "neutral": CheckStatus.NEUTRAL,
        "skipped": CheckStatus.SKIPPED,
        "stale": CheckStatus.SKIPPED,
    }.get(conclusion, CheckStatus.ERROR)


def map_checks(check_runs_payload: dict, required_checks: list[str]) -> list[Check]:
    """Map the /check-runs payload. A check is 'required' when it's named in
    ``required_checks``; an empty list means treat every check as required."""
    runs = check_runs_payload.get("check_runs", [])
    out: list[Check] = []
    for run in runs:
        name = run.get("name", "")
        required = (not required_checks) or (name in required_checks)
        out.append(
            Check(
                name=name,
                status=_check_status(run),
                required=required,
                completed_at=_dt(run.get("completed_at")),
                url=run.get("html_url"),
            )
        )
    return out


_LEGACY_STATE = {
    "success": CheckStatus.SUCCESS,
    "failure": CheckStatus.FAILURE,
    "error": CheckStatus.ERROR,
    "pending": CheckStatus.PENDING,
}


def map_statuses(
    status_payload: dict,
    required_checks: list[str],
    exclude_contexts: set[str] | None = None,
) -> list[Check]:
    """Map the legacy combined-status payload (/commits/{sha}/status) into Checks.

    This is the OTHER half of GitHub's CI surface: many integrations (Harness
    included) report via the legacy Status API rather than check-runs. ``context``
    is the status's name. ``exclude_contexts`` drops our own write-back status so
    the service never treats its own ``pr-health`` status as a CI check.
    """
    exclude = exclude_contexts or set()
    out: list[Check] = []
    seen: set[str] = set()
    for status in status_payload.get("statuses", []):
        context = status.get("context", "")
        if context in exclude or context in seen:
            continue
        seen.add(context)
        required = (not required_checks) or (context in required_checks)
        out.append(
            Check(
                name=context,
                status=_LEGACY_STATE.get((status.get("state") or "").lower(), CheckStatus.ERROR),
                required=required,
                completed_at=_dt(status.get("updated_at")),
                url=status.get("target_url"),
            )
        )
    return out


def map_commits(commits: list[dict]) -> list[Commit]:
    out: list[Commit] = []
    for c in commits:
        commit = c.get("commit") or {}
        author_block = commit.get("author") or {}
        login = (c.get("author") or {}).get("login")
        out.append(
            Commit(
                sha=c.get("sha", ""),
                author=login or author_block.get("name", "") or "unknown",
                message=commit.get("message", ""),
                committed_at=_dt(author_block.get("date")),
            )
        )
    return out


def map_pr_refs(pulls: list[dict], repo: str) -> list[PRRef]:
    return [
        PRRef(
            provider=PROVIDER,
            repo=repo,
            number=int(p["number"]),
            commit_sha=(p.get("head") or {}).get("sha", ""),
            title=p.get("title") or "",
        )
        for p in pulls
    ]
