"""Harness Code (Gitness-based) JSON -> canonical domain models.

PURE mapping functions. This is the proof that providers are "just adapters":
the same canonical models come out, so analyzers/scoring/persistence are unchanged
whether the PR came from GitHub or Harness SCM. Gitness timestamps are epoch millis.
"""
from __future__ import annotations

from datetime import datetime, timezone

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

PROVIDER = "harness"


def _dt_ms(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _state(pr: dict) -> PRState:
    if pr.get("merged") or (pr.get("state") == "merged"):
        return PRState.MERGED
    if pr.get("state") == "closed":
        return PRState.CLOSED
    return PRState.OPEN


def _author(block: dict | None) -> str:
    block = block or {}
    return block.get("display_name") or block.get("email") or "unknown"


def map_pull_request(pr: dict, repo: str) -> PullRequest:
    title = pr.get("title") or ""
    body = pr.get("description") or ""
    source_branch = pr.get("source_branch", "")
    return PullRequest(
        provider=PROVIDER,
        repo=repo,
        number=int(pr["number"]),
        title=title,
        description=body,
        author=_author(pr.get("author")),
        state=_state(pr),
        source_branch=source_branch,
        target_branch=pr.get("target_branch", ""),
        commit_sha=pr.get("source_sha", ""),
        base_commit_sha=pr.get("merge_base_sha", ""),
        opened_at=_dt_ms(pr.get("created")),
        merged_at=_dt_ms(pr.get("merged")),
        closed_at=_dt_ms(pr.get("closed")),
        jira_issue_id=extract_jira_key(title, body, source_branch),
        provider_pr_id=str(pr["number"]),
    )


def map_diff(files: list[dict], stats: dict | None = None) -> Diff:
    diff_files = [
        DiffFile(
            filename=f.get("path", ""),
            additions=int(f.get("additions", 0)),
            deletions=int(f.get("deletions", 0)),
            status=f.get("status", "modified"),
        )
        for f in files
    ]
    stats = stats or {}
    additions = int(stats.get("additions", sum(f.additions for f in diff_files)))
    deletions = int(stats.get("deletions", sum(f.deletions for f in diff_files)))
    files_changed = int(stats.get("files_changed", len(diff_files)))
    return Diff(files_changed=files_changed, additions=additions, deletions=deletions, files=diff_files)


_REVIEW_DECISION = {
    "approved": ReviewState.APPROVED,
    "changereq": ReviewState.CHANGES_REQUESTED,
    "reviewed": ReviewState.COMMENTED,
    "pending": ReviewState.PENDING,
}


def map_reviews(reviewers: list[dict]) -> list[Review]:
    out: list[Review] = []
    for r in reviewers:
        decision = (r.get("review_decision") or "pending").lower()
        out.append(
            Review(
                reviewer=_author(r.get("reviewer")),
                state=_REVIEW_DECISION.get(decision, ReviewState.COMMENTED),
                submitted_at=_dt_ms(r.get("updated")),
            )
        )
    return out


_CHECK_STATUS = {
    "success": CheckStatus.SUCCESS,
    "failure": CheckStatus.FAILURE,
    "error": CheckStatus.FAILURE,
    "running": CheckStatus.PENDING,
    "pending": CheckStatus.PENDING,
    "skipped": CheckStatus.SKIPPED,
}


def map_checks(checks: list[dict], required_checks: list[str]) -> list[Check]:
    out: list[Check] = []
    for c in checks:
        name = c.get("identifier") or c.get("name", "")
        if "required" in c:
            required = bool(c["required"])
        else:
            required = (not required_checks) or (name in required_checks)
        out.append(
            Check(
                name=name,
                status=_CHECK_STATUS.get((c.get("status") or "").lower(), CheckStatus.ERROR),
                required=required,
                completed_at=_dt_ms(c.get("ended")),
                url=c.get("link"),
            )
        )
    return out


def map_commits(commits: list[dict]) -> list[Commit]:
    out: list[Commit] = []
    for c in commits:
        author_block = (c.get("author") or {}).get("identity") or {}
        out.append(
            Commit(
                sha=c.get("sha", ""),
                author=author_block.get("name") or author_block.get("email") or "unknown",
                message=c.get("message") or c.get("title", ""),
                committed_at=_dt_ms((c.get("author") or {}).get("when")),
            )
        )
    return out


def map_pr_refs(pulls: list[dict], repo: str) -> list[PRRef]:
    return [
        PRRef(
            provider=PROVIDER,
            repo=repo,
            number=int(p["number"]),
            commit_sha=p.get("source_sha", ""),
            title=p.get("title") or "",
        )
        for p in pulls
    ]
