"""GitHubProvider — real SCM adapter over GitHub REST v3 (httpx + PAT).

Fetches raw JSON and delegates ALL shaping to providers.mappers.github_mapper, so
this module only knows endpoints/auth/pagination, never canonical model fields.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from app.domain.models import Check, Commit, Diff, PRRef, PullRequest, Review
from app.providers.base import SCMProvider
from app.providers.mappers import github_mapper as gh

_PER_PAGE = 100
_MAX_PAGES = 30  # safety cap


class GitHubProvider(SCMProvider):
    name = "github"

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.github.com",
        required_checks: list[str] | None = None,
        timeout: float = 20.0,
        exclude_status_contexts: set[str] | None = None,
    ) -> None:
        self.required_checks = required_checks or []
        # Drop our own write-back commit status (writeback_service.STATUS_CONTEXT)
        # so the service never scores its own "pr-health" status as a CI check.
        self.exclude_status_contexts = exclude_status_contexts or {"pr-health"}
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=api_url.rstrip("/"), headers=headers, timeout=timeout)

    # ----------------------------------------------------------------- helpers
    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None) -> list[dict]:
        params = dict(params or {})
        params["per_page"] = _PER_PAGE
        items: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            params["page"] = page
            resp = self._client.get(path, params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if len(batch) < _PER_PAGE:
                break
        return items

    # ----------------------------------------------------------------- reads
    def get_pull_request(self, repo: str, pr_id: int) -> PullRequest:
        return gh.map_pull_request(self._get(f"/repos/{repo}/pulls/{pr_id}"), repo)

    def get_diff(self, repo: str, pr_id: int) -> Diff:
        files = self._paginate(f"/repos/{repo}/pulls/{pr_id}/files")
        return gh.map_diff(files)

    def get_reviews(self, repo: str, pr_id: int) -> list[Review]:
        return gh.map_reviews(self._paginate(f"/repos/{repo}/pulls/{pr_id}/reviews"))

    def get_checks(self, repo: str, sha: str) -> list[Check]:
        """All build statuses for the head commit: modern check-runs AND legacy
        commit statuses (Harness/Jenkins/etc. report here), merged + de-duped."""
        runs = self._get(f"/repos/{repo}/commits/{sha}/check-runs", {"per_page": _PER_PAGE})
        checks = gh.map_checks(runs, self.required_checks)
        seen = {c.name for c in checks}

        status = self._get(f"/repos/{repo}/commits/{sha}/status")
        for check in gh.map_statuses(status, self.required_checks, self.exclude_status_contexts):
            if check.name not in seen:
                checks.append(check)
                seen.add(check.name)
        return checks

    def get_commits(self, repo: str, pr_id: int) -> list[Commit]:
        return gh.map_commits(self._paginate(f"/repos/{repo}/pulls/{pr_id}/commits"))

    def list_pull_requests(self, repo: str, since: datetime) -> list[PRRef]:
        pulls = self._paginate(
            f"/repos/{repo}/pulls",
            {"state": "all", "sort": "created", "direction": "desc"},
        )
        kept = [p for p in pulls if (gh._dt(p.get("created_at")) or since) >= since]
        return gh.map_pr_refs(kept, repo)

    # ----------------------------------------------------------------- writes
    def post_comment(self, repo: str, pr_id: int, body: str) -> None:
        resp = self._client.post(f"/repos/{repo}/issues/{pr_id}/comments", json={"body": body})
        resp.raise_for_status()

    def set_status(self, repo: str, sha: str, state: str, context: str, description: str) -> None:
        resp = self._client.post(
            f"/repos/{repo}/statuses/{sha}",
            json={"state": state, "context": context, "description": description[:140]},
        )
        resp.raise_for_status()

    # ----------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubProvider":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
