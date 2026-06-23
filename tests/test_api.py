"""
Integration tests for the API endpoints.
The conftest.py replaces the global SQLAlchemy engine with SQLite in-memory
and patches init_db to a no-op before these tests run.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.db.session as _db_session
from app.db.session import get_db


def make_client():
    """Build a TestClient with the SQLite session injected."""
    from app.main import create_app
    app = create_app()

    TestSession = sessionmaker(bind=_db_session.engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client():
    with make_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    with patch("app.api.health.check_db_health", return_value="healthy"), \
         patch("app.api.health.check_redis_health", return_value="healthy"), \
         patch("app.api.health.check_worker_health", return_value="active (1 workers)"):
        response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["database"] == "healthy"
    assert data["redis"] == "healthy"
    assert data["status"] == "healthy"


# ---------------------------------------------------------------------------
# SCM events endpoint
# ---------------------------------------------------------------------------

def test_scm_event_queues_job(client):
    with patch("app.api.events.enqueue_scm_event", return_value="test-job-123"):
        response = client.post(
            "/api/events/scm",
            json={
                "provider": "harness",
                "event": "pr.opened",
                "repository": "myorg/myrepo",
                "metadata": {"pr_number": 42},
            },
        )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert data["job_id"] == "test-job-123"


def test_scm_event_missing_fields(client):
    response = client.post("/api/events/scm", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PR list endpoint
# ---------------------------------------------------------------------------

def test_pr_list_unknown_prs(client):
    response = client.post("/api/pr/list", json={"pr_ids": [9999, 9998]})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    for item in data:
        assert item["severity_score"] == 0
        assert item["severity_color"] == "unknown"


def test_pr_list_empty_ids_rejected(client):
    response = client.post("/api/pr/list", json={"pr_ids": []})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PR detail endpoint
# ---------------------------------------------------------------------------

def test_pr_detail_not_found(client):
    response = client.get("/api/pr/99999")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "not_found"


# ---------------------------------------------------------------------------
# PR refresh endpoint
# ---------------------------------------------------------------------------

def test_pr_refresh_not_found(client):
    response = client.post("/api/pr/99999/refresh")
    assert response.status_code == 404
