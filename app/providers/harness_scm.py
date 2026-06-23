"""HarnessSCMProvider — Harness Code (Gitness-based) adapter.

Interface-complete this round: it implements the full SCMProvider port over Harness
Code's REST API (auth via ``x-api-key``; account/org/project routing centralized in
``_repo_ref``). The canonical mapping is in harness_mapper and is unit-tested against
captured-shape fixtures; live calls require a configured Harness Code instance.

The point it demonstrates: GitHub and Harness SCM differ ONLY here and in the mapper.
Everything downstream (analyzers, scoring, persistence, API) is provider-blind.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx

from app.domain.models import Check, Commit, Diff, PRRef, PullRequest, Review
from app.providers.base import SCMProvider
from app.providers.mappers import harness_mapper as hm

_API_PREFIX = "/code/api/v1"


class HarnessSCMProvider(SCMProvider):
    name = "harness"

    def __init__(
        self,
        token: str,
        api_url: str = "https://app.harness.io",
        account_id: str = "",
        org_id: str = "",
        project_id: str = "",
        required_checks: list[str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.account_id = account_id
        self.org_id = org_id
        self.project_id = project_id
        self.required_checks = required_checks or []
        headers = {"Accept": "application/json"}
        if token:
            headers["x-api-key"] = token
        self._client = httpx.Client(
            base_url=api_url.rstrip("/") + _API_PREFIX,
            headers=headers,
            params={"accountIdentifier": account_id, "orgIdentifier": org_id, "projectIdentifier": project_id},
            timeout=timeout,
        )

    def _repo_ref(self, repo: str) -> str:
        """Harness Code addresses a repo by a routed path. Centralized so the rest
        of the adapter is path-agnostic; adjust here for your instance's routing."""
        return quote(repo, safe="")

    def _get(self, path: str, params: dict | None = None) -> object:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # ----------------------------------------------------------------- reads
    def get_pull_request(self, repo: str, pr_id: int) -> PullRequest:
        data = self._get(f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}")
        return hm.map_pull_request(data, repo)

    def get_diff(self, repo: str, pr_id: int) -> Diff:
        pr = self._get(f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}")
        files = self._get(f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}/diff")
        if isinstance(files, dict):  # some instances wrap file stats under a key
            files = files.get("files", [])
        return hm.map_diff(files or [], (pr or {}).get("stats"))

    def get_reviews(self, repo: str, pr_id: int) -> list[Review]:
        data = self._get(f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}/reviewers")
        return hm.map_reviews(data or [])

    def get_checks(self, repo: str, sha: str) -> list[Check]:
        data = self._get(f"/repos/{self._repo_ref(repo)}/checks/commits/{sha}")
        if isinstance(data, dict):
            data = data.get("checks", [])
        return hm.map_checks(data or [], self.required_checks)

    def get_commits(self, repo: str, pr_id: int) -> list[Commit]:
        data = self._get(f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}/commits")
        if isinstance(data, dict):
            data = data.get("commits", [])
        return hm.map_commits(data or [])

    def list_pull_requests(self, repo: str, since: datetime) -> list[PRRef]:
        data = self._get(f"/repos/{self._repo_ref(repo)}/pullreq", {"state": "all", "limit": 100})
        if isinstance(data, dict):
            data = data.get("pull_requests", [])
        return hm.map_pr_refs(data or [], repo)

    # ----------------------------------------------------------------- writes
    def post_comment(self, repo: str, pr_id: int, body: str) -> None:
        resp = self._client.post(
            f"/repos/{self._repo_ref(repo)}/pullreq/{pr_id}/comments", json={"text": body}
        )
        resp.raise_for_status()

    def set_status(self, repo: str, sha: str, state: str, context: str, description: str) -> None:
        # Harness Code surfaces external status via commit checks.
        payload = {
            "identifier": context,
            "status": "success" if state == "success" else "failure",
            "summary": description[:140],
        }
        resp = self._client.put(f"/repos/{self._repo_ref(repo)}/checks/commits/{sha}", json=payload)
        resp.raise_for_status()

    # ----------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HarnessSCMProvider":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
