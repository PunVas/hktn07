"""Provider resolution by name. EDGE — wires concrete adapters from settings.

The request declares its provider explicitly (no payload sniffing). Phase D adds
the Harness SCM adapter here; the rest of the system never changes.
"""
from __future__ import annotations

from app.config import Settings
from app.providers.base import SCMProvider
from app.providers.github import GitHubProvider
from app.providers.harness_scm import HarnessSCMProvider


def get_provider(name: str, settings: Settings) -> SCMProvider:
    if name == "github":
        return GitHubProvider(
            token=settings.github_token,
            api_url=settings.github_api_url,
            required_checks=settings.required_checks_list,
        )
    if name == "harness":
        return HarnessSCMProvider(
            token=settings.harness_token,
            api_url=settings.harness_api_url,
            account_id=settings.harness_account_id,
            org_id=settings.harness_org_id,
            project_id=settings.harness_project_id,
            required_checks=settings.required_checks_list,
        )
    raise ValueError(f"Unknown provider: {name!r}")
