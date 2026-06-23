"""
Harness Code Repository API client.
All external HTTP calls are isolated here.
Retries transient failures via tenacity.
"""
from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging
from typing import Any

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HarnessAPIError(Exception):
    """Raised when the Harness API returns a non-retryable error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class HarnessTransientError(Exception):
    """Raised on retryable failures (5xx, timeouts)."""


class HarnessClient:
    """
    Thin wrapper around the Harness Code Repository REST API.
    Uses httpx with connection pooling and automatic retries.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.harness_base_url
        self._api_key = settings.harness_api_key
        self._account_id = settings.harness_account_id
        self._org_id = settings.harness_org_id
        self._project_id = settings.harness_project_id
        self._timeout = httpx.Timeout(30.0, connect=10.0)

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            headers={
                "x-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
        )

    def _build_repo_path(self, repo: str) -> str:
        """
        Build the Harness repo path from the full repository name.
        The Harness Code API path format:
        /code/api/v1/repos/{repo}/pullreq/{pr_id}
        where repo may include org/project prefix for Harness-scoped repos.
        """
        return repo

    @retry(
        retry=retry_if_exception_type(HarnessTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def get_pull_request(self, repo: str, pr_id: int) -> dict[str, Any]:
        """
        Fetch a single pull request from the Harness Code API.

        GET /code/api/v1/repos/{repo}/pullreq/{pr_id}

        Returns the raw JSON response dict.
        """
        repo_path = self._build_repo_path(repo)
        url = f"/code/api/v1/repos/{repo_path}/pullreq/{pr_id}"
        params = {
            "accountIdentifier": self._account_id,
            "orgIdentifier": self._org_id,
            "projectIdentifier": self._project_id,
        }

        logger.info(
            "Calling Harness API",
            extra={"url": url, "pr_id": pr_id, "repo": repo},
        )

        with self._make_client() as client:
            try:
                response = client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise HarnessTransientError(f"Timeout fetching PR {pr_id}: {exc}") from exc
            except httpx.RequestError as exc:
                raise HarnessTransientError(f"Network error fetching PR {pr_id}: {exc}") from exc

        if response.status_code in _RETRYABLE_STATUS_CODES:
            raise HarnessTransientError(
                f"Harness API returned {response.status_code} for PR {pr_id}"
            )

        if response.status_code == 404:
            raise HarnessAPIError(404, f"PR {pr_id} not found in repo '{repo}'")

        if response.status_code >= 400:
            raise HarnessAPIError(
                response.status_code,
                f"Harness API error {response.status_code}: {response.text[:256]}",
            )

        data: dict[str, Any] = response.json()
        logger.info(
            "Harness API response received",
            extra={"pr_id": pr_id, "status_code": response.status_code},
        )
        return data

    def get_pull_request_files(self, repo: str, pr_id: int) -> list[dict[str, Any]]:
        """
        Fetch files changed in a pull request.

        GET /code/api/v1/repos/{repo}/pullreq/{pr_id}/files

        Returns list of file diff objects.
        """
        repo_path = self._build_repo_path(repo)
        url = f"/code/api/v1/repos/{repo_path}/pullreq/{pr_id}/files"
        params = {
            "accountIdentifier": self._account_id,
            "orgIdentifier": self._org_id,
            "projectIdentifier": self._project_id,
        }

        with self._make_client() as client:
            try:
                response = client.get(url, params=params)
            except (httpx.TimeoutException, httpx.RequestError):
                # files endpoint failure is non-fatal; return empty
                logger.warning(
                    "Failed to fetch PR files, continuing with empty file list",
                    extra={"pr_id": pr_id},
                )
                return []

        if response.status_code != 200:
            logger.warning(
                "PR files endpoint returned non-200",
                extra={"pr_id": pr_id, "status_code": response.status_code},
            )
            return []

        data = response.json()
        # Harness returns {"files": [...]} or directly a list
        if isinstance(data, list):
            return data
        return data.get("files", [])

    def get_pull_request_reviewers(self, repo: str, pr_id: int) -> list[dict[str, Any]]:
        """
        Fetch the reviewers assigned to a pull request.

        GET /code/api/v1/repos/{repo}/pullreq/{pr_id}/reviewers

        Returns a list of reviewer objects (one per assigned reviewer).
        Reviewer-endpoint failures are non-fatal; an empty list is returned
        in that case.
        """
        repo_path = self._build_repo_path(repo)
        url = f"/code/api/v1/repos/{repo_path}/pullreq/{pr_id}/reviewers"
        params = {
            "accountIdentifier": self._account_id,
            "orgIdentifier": self._org_id,
            "projectIdentifier": self._project_id,
        }

        with self._make_client() as client:
            try:
                response = client.get(url, params=params)
            except (httpx.TimeoutException, httpx.RequestError):
                logger.warning(
                    "Failed to fetch PR reviewers, continuing with empty list",
                    extra={"pr_id": pr_id},
                )
                return []

        if response.status_code != 200:
            logger.warning(
                "PR reviewers endpoint returned non-200",
                extra={"pr_id": pr_id, "status_code": response.status_code},
            )
            return []

        data = response.json()
        # Harness returns a list of reviewer objects, or {"reviewer": [...]}.
        if isinstance(data, list):
            return data
        return data.get("reviewer", [])


# Module-level singleton
_client: HarnessClient | None = None


def get_harness_client() -> HarnessClient:
    global _client
    if _client is None:
        _client = HarnessClient()
    return _client
