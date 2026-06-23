"""
SCM Provider Detection Utility.
Detects the actual SCM provider from repository URL.
"""
from __future__ import annotations

from urllib.parse import urlparse


def detect_scm_provider(repo_url: str | None, fallback_provider: str = "harness") -> str:
    """
    Detect the actual SCM provider from a repository URL.

    Args:
        repo_url: Full repository URL (e.g., https://github.com/owner/repo)
        fallback_provider: Provider to use if detection fails

    Returns:
        Detected provider name: "github", "gitlab", "bitbucket", or fallback
    """
    if not repo_url:
        return fallback_provider

    try:
        parsed = urlparse(repo_url.lower())
        hostname = parsed.hostname or ""

        # GitHub detection
        if "github.com" in hostname or "github.dev" in hostname:
            return "github"

        # GitLab detection
        if "gitlab.com" in hostname or "gitlab" in hostname:
            return "gitlab"

        # Bitbucket detection
        if "bitbucket.org" in hostname or "bitbucket.com" in hostname:
            return "bitbucket"

        # Harness Code (Gitness) detection
        if "harness.io" in hostname or "gitness" in hostname:
            return "harness"

    except Exception:
        pass

    return fallback_provider


def extract_repo_slug_from_url(repo_url: str | None) -> str | None:
    """
    Extract the repository slug (owner/repo) from a URL.

    Args:
        repo_url: Full repository URL

    Returns:
        Repository slug in format "owner/repo" or None
    """
    if not repo_url:
        return None

    try:
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/")

        # Remove .git suffix if present
        if path.endswith(".git"):
            path = path[:-4]

        # For GitHub/GitLab/Bitbucket, path is typically "owner/repo"
        parts = path.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"

    except Exception:
        pass

    return None
