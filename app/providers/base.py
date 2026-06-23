"""SCMProvider — the port every SCM adapter implements.

Adapters return CANONICAL domain models (never provider-native JSON). The rest of
the system is provider-blind; adding GitLab/Bitbucket later = a new class here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.models import Check, Commit, Diff, PRRef, PullRequest, Review


class SCMProvider(ABC):
    #: provider identifier, e.g. "github" / "harness"
    name: str

    @abstractmethod
    def get_pull_request(self, repo: str, pr_id: int) -> PullRequest: ...

    @abstractmethod
    def get_diff(self, repo: str, pr_id: int) -> Diff: ...

    @abstractmethod
    def get_reviews(self, repo: str, pr_id: int) -> list[Review]: ...

    @abstractmethod
    def get_checks(self, repo: str, sha: str) -> list[Check]: ...

    @abstractmethod
    def get_commits(self, repo: str, pr_id: int) -> list[Commit]: ...

    @abstractmethod
    def list_pull_requests(self, repo: str, since: datetime) -> list[PRRef]: ...

    @abstractmethod
    def post_comment(self, repo: str, pr_id: int, body: str) -> None: ...

    @abstractmethod
    def set_status(
        self, repo: str, sha: str, state: str, context: str, description: str
    ) -> None: ...
