"""
App-level repository alias.
Workers and services use `from app import repository as repo`
and then call `repo.upsert_repository(...)` etc.
"""
from app.repository.pr_repository import (
    upsert_repository,
    get_repository_by_name,
    upsert_pull_request,
    get_pull_request_by_pr_id,
    get_pull_requests_by_pr_ids,
    upsert_pr_analysis,
    get_analysis_for_pr,
    create_job,
    update_job_status,
    increment_job_retry,
    get_job,
    append_processing_log,
)

__all__ = [
    "upsert_repository",
    "get_repository_by_name",
    "upsert_pull_request",
    "get_pull_request_by_pr_id",
    "get_pull_requests_by_pr_ids",
    "upsert_pr_analysis",
    "get_analysis_for_pr",
    "create_job",
    "update_job_status",
    "increment_job_retry",
    "get_job",
    "append_processing_log",
]
