"""
Smoke test script — validates the backend is running correctly.
Run after docker compose up --build.

Usage:
    python scripts/smoke_test.py [--base-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

import httpx


def run_smoke_tests(base_url: str) -> bool:
    client = httpx.Client(base_url=base_url, timeout=10.0)
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))
        if condition:
            passed += 1
        else:
            failed += 1

    print(f"\n=== PR Guardian Smoke Tests ===")
    print(f"Base URL: {base_url}\n")

    # Health check
    print("1. Health Check")
    try:
        r = client.get("/api/health")
        check("Status code 200", r.status_code == 200)
        data = r.json()
        check("Has database field", "database" in data)
        check("Has redis field", "redis" in data)
        check("Has status field", "status" in data)
    except Exception as e:
        check("Health endpoint reachable", False, str(e))

    # SCM event
    print("\n2. SCM Event Endpoint")
    try:
        r = client.post(
            "/api/events/scm",
            json={
                "provider": "harness",
                "event": "pr.opened",
                "repository": "smoke-test/repo",
                "metadata": {"pr_number": 1},
            },
        )
        check("Status code 202", r.status_code == 202)
        data = r.json()
        check("Status is queued", data.get("status") == "queued")
        check("Has job_id", bool(data.get("job_id")))
    except Exception as e:
        check("SCM event endpoint reachable", False, str(e))

    # PR list
    print("\n3. PR List Endpoint")
    try:
        r = client.post("/api/pr/list", json={"pr_ids": [1, 2, 3]})
        check("Status code 200", r.status_code == 200)
        data = r.json()
        check("Returns list", isinstance(data, list))
        check("Returns 3 items", len(data) == 3)
        for item in data:
            check("Has pr_id", "pr_id" in item)
            check("Has severity_score", "severity_score" in item)
    except Exception as e:
        check("PR list endpoint reachable", False, str(e))

    # PR detail (unknown — expect 404)
    print("\n4. PR Detail Endpoint (unknown PR)")
    try:
        r = client.get("/api/pr/99999")
        check("Status code 404", r.status_code == 404)
        data = r.json()
        check("Has error field", "error" in data.get("detail", {}))
    except Exception as e:
        check("PR detail endpoint reachable", False, str(e))

    # OpenAPI docs
    print("\n5. OpenAPI Docs")
    try:
        r = client.get("/docs")
        check("Docs reachable", r.status_code == 200)
    except Exception as e:
        check("Docs reachable", False, str(e))

    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    return failed == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    success = run_smoke_tests(args.base_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
