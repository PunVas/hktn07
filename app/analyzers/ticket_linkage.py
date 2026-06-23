"""Extract JIRA ticket references from PR metadata."""
from __future__ import annotations

import re

_JIRA_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_key(title: str, body: str, branch: str) -> str | None:
    """
    Extract the first JIRA issue key found in title, body, or branch name.
    Returns None if no JIRA key is found.

    Examples:
        "ABC-123 Fix bug" -> "ABC-123"
        "feature/XYZ-456-new-feature" -> "XYZ-456"
    """
    for text in (title, body, branch):
        if not text:
            continue
        match = _JIRA_PATTERN.search(text)
        if match:
            return match.group(1)
    return None
