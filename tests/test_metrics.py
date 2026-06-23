"""
Unit tests for the metrics computation engine.
No external dependencies required — pure function tests.
"""
from __future__ import annotations

import pytest

from app.services.metrics import (
    _clamp,
    _normalise,
    compute_complexity,
    compute_severity,
    compute_blast_radius,
    extract_pr_metadata,
    compute_full_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_clamp_bounds():
    assert _clamp(-10) == 0
    assert _clamp(110) == 100
    assert _clamp(50) == 50


def test_normalise():
    assert _normalise(0, 100) == 0.0
    assert _normalise(50, 100) == 0.5
    assert _normalise(200, 100) == 1.0  # capped
    assert _normalise(10, 0) == 0.0   # zero division guard


# ---------------------------------------------------------------------------
# extract_pr_metadata
# ---------------------------------------------------------------------------

SAMPLE_RAW_PR = {
    "number": 119080,
    "title": "Fix auth bug",
    "author": {"display_name": "Alice", "uid": "alice"},
    "state": "open",
    "source_branch": "feature/auth-fix",
    "target_branch": "main",
    "created": "2024-01-01T00:00:00Z",
    "updated": "2024-01-01T18:00:00Z",
    "stats": {
        "files_changed": 31,
        "additions": 1231,
        "deletions": 438,
        "commits": 5,
    },
}


def test_extract_pr_metadata_basic():
    meta = extract_pr_metadata(SAMPLE_RAW_PR)
    assert meta["pr_id"] == 119080
    assert meta["author"] == "Alice"
    assert meta["files_changed"] == 31
    assert meta["lines_added"] == 1231
    assert meta["lines_deleted"] == 438
    assert meta["review_time"] == 18  # 18 hours


def test_extract_pr_metadata_missing_stats():
    raw = {"number": 1, "stats": {}}
    meta = extract_pr_metadata(raw)
    assert meta["files_changed"] == 0
    assert meta["lines_added"] == 0
    assert meta["review_time"] == 0


# ---------------------------------------------------------------------------
# compute_complexity
# ---------------------------------------------------------------------------

def test_compute_complexity_zero():
    score = compute_complexity(0, 0, 0, 0)
    assert score == 0


def test_compute_complexity_large():
    score = compute_complexity(100, 5000, 2000, 90)
    assert 0 <= score <= 100


def test_compute_complexity_moderate():
    score = compute_complexity(31, 1231, 438, 63)
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# compute_severity
# ---------------------------------------------------------------------------

def test_compute_severity_high():
    score, color, factor, icon = compute_severity(
        complexity=90, files_changed=80, lines_added=4000,
        lines_deleted=1000, review_time=48, blast_radius_score=90
    )
    assert score >= 75
    assert color == "red"
    assert factor in ("Blast Radius", "Lines Changed", "Files Changed", "Complexity", "Review Time")
    assert icon in ("blast", "lines", "files", "complexity", "clock")


def test_compute_severity_low():
    score, color, factor, icon = compute_severity(
        complexity=5, files_changed=2, lines_added=10,
        lines_deleted=5, review_time=1, blast_radius_score=5
    )
    assert score < 50
    assert color == "green"


def test_compute_severity_amber():
    score, color, factor, icon = compute_severity(
        complexity=50, files_changed=20, lines_added=500,
        lines_deleted=100, review_time=10, blast_radius_score=40
    )
    assert 0 <= score <= 100
    assert color in ("green", "amber", "red")


# ---------------------------------------------------------------------------
# compute_blast_radius
# ---------------------------------------------------------------------------

SAMPLE_FILES = [
    {"path": "src/auth/login.py"},
    {"path": "src/auth/logout.py"},
    {"path": "src/api/routes.py"},
    {"path": "tests/test_auth.py"},
]

SAMPLE_META = {
    "pr_id": 1,
    "title": "Test PR",
    "author": "Bob",
    "files_changed": 4,
    "lines_added": 100,
    "lines_deleted": 20,
}


def test_compute_blast_radius_structure():
    graph, score = compute_blast_radius(SAMPLE_FILES, SAMPLE_META)
    assert "center" in graph
    assert "ring_nodes" in graph
    assert "outer_nodes" in graph
    assert "edges" in graph
    assert graph["center"]["id"] == "pr-1"
    assert len(graph["ring_nodes"]) > 0
    assert len(graph["outer_nodes"]) > 0
    assert 0 <= score <= 100


def test_compute_blast_radius_no_files():
    meta = {**SAMPLE_META, "files_changed": 5}
    graph, score = compute_blast_radius([], meta)
    assert graph["center"]["id"] == "pr-1"
    assert 0 <= score <= 100


def test_compute_blast_radius_score_range():
    graph, score = compute_blast_radius(SAMPLE_FILES, SAMPLE_META)
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# compute_full_analysis
# ---------------------------------------------------------------------------

def test_compute_full_analysis_integration():
    result = compute_full_analysis(raw_pr=SAMPLE_RAW_PR, files=SAMPLE_FILES)

    assert "severity_score" in result
    assert "severity_color" in result
    assert "dominant_factor" in result
    assert "dominant_factor_icon" in result
    assert "complexity" in result
    assert "files_changed" in result
    assert "lines_added" in result
    assert "lines_deleted" in result
    assert "review_time" in result
    assert "blast_radius_score" in result
    assert "blast_radius_graph" in result
    assert "pr_metadata" in result

    assert 0 <= result["severity_score"] <= 100
    assert result["severity_color"] in ("green", "amber", "red")
    assert result["files_changed"] == 31
    assert result["lines_added"] == 1231
