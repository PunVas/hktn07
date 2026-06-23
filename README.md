# PR Guardian — Backend

Backend service for **PR Guardian**, a Chrome Extension that shows continuous PR health metrics directly in Harness Code.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 (SQLAlchemy 2.x, no Alembic) |
| Queue | Redis 7 + RQ |
| HTTP Client | httpx + tenacity |
| Config | pydantic-settings + `.env` |
| Container | Docker Compose |

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env and fill in your Harness credentials:
#   HARNESS_API_KEY
#   HARNESS_ACCOUNT_ID
#   HARNESS_ORG_ID
#   HARNESS_PROJECT_ID
```

### 2. Start

```bash
docker compose up --build
```

This starts four services:
- `postgres` — PostgreSQL database
- `redis` — Redis broker
- `backend` — FastAPI API server on port 8000
- `worker` — RQ worker process

Tables are created automatically on startup — no migrations needed.

### 3. Verify

```bash
# Health check
curl http://localhost:8000/api/health

# Send a test SCM event
./scripts/seed_test_event.sh 119080 myorg/myrepo

# Run smoke tests
python scripts/smoke_test.py

# Interactive API docs
open http://localhost:8000/docs
```

---

## API Reference

### `POST /api/events/scm`

Receive a Harness SCM webhook trigger. Immediately returns HTTP 202 and enqueues background processing.

```json
{
  "provider": "harness",
  "event": "pr.opened",
  "repository": "myorg/myrepo",
  "metadata": {
    "pr_number": 119080
  }
}
```

Response:
```json
{ "status": "queued", "job_id": "..." }
```

---

### `POST /api/pr/list`

Return severity summary for multiple PRs. Served from DB cache only — no external API calls.

```json
{ "pr_ids": [119080, 119081] }
```

Response:
```json
[
  {
    "pr_id": 119080,
    "severity_score": 82,
    "severity_color": "red",
    "dominant_factor": "Blast Radius",
    "dominant_factor_icon": "blast"
  }
]
```

---

### `GET /api/pr/{pr_id}`

Return full PR detail for the insights panel. Served from DB cache only.

Response:
```json
{
  "pr_id": 119080,
  "severity_score": 82,
  "dominant_factor": "Blast Radius",
  "metrics": {
    "complexity": 74,
    "files_changed": 31,
    "lines_added": 1231,
    "lines_deleted": 438,
    "review_time": 18,
    "blast_radius_score": 63
  },
  "blast_radius": {
    "center": {},
    "ring_nodes": [],
    "outer_nodes": [],
    "edges": []
  },
  "last_updated": "2024-01-01T18:00:00Z"
}
```

---

### `POST /api/pr/{pr_id}/refresh`

Enqueue a re-analysis job for the PR. Returns HTTP 202.

---

### `GET /api/health`

```json
{
  "database": "healthy",
  "redis": "healthy",
  "worker": "active (1 workers)",
  "status": "healthy"
}
```

---

## Architecture

```
Harness Trigger
       │
       ▼
POST /api/events/scm
       │
       ▼
 FastAPI validates
       │
       ▼
Push to Redis Queue (RQ)
       │
       ▼
Return HTTP 202
       │
       ▼ (async)
Worker consumes event
       │
       ▼
Calls Harness PR API (httpx + tenacity retries)
       │
       ▼
Compute metrics:
  - Severity Score (0-100)
  - Dominant Factor
  - Complexity
  - Blast Radius Graph (JSON for React Flow)
       │
       ▼
UPSERT PostgreSQL
       │
       ▼
Chrome Extension → GET /api/pr/{id}
       │
       ▼
Backend serves cached DB result (ZERO external calls)
```

## Metrics Computation

### Severity Score (0–100)

Weighted composite:

| Factor | Weight |
|---|---|
| Complexity | 25% |
| Blast Radius | 30% |
| Lines Changed | 20% |
| Files Changed | 15% |
| Review Time | 10% |

**Colors:**
- 🔴 Red: ≥ 75
- 🟡 Amber: 50–74
- 🟢 Green: < 50

### Blast Radius Graph

Returns logical graph data only — no coordinates. The Chrome Extension's React Flow renders x/y positions.

Structure:
- `center` — the PR itself
- `ring_nodes` — affected directories
- `outer_nodes` — individual changed files
- `edges` — connections between nodes

---

## Project Structure

```
backend/
├── app/
│   ├── api/            # FastAPI routers (thin, no logic)
│   ├── config/         # Settings via pydantic-settings
│   ├── db/             # Engine, session, Base
│   ├── models/         # SQLAlchemy ORM models
│   ├── schemas/        # Pydantic v2 request/response schemas
│   ├── repository/     # All DB access (no business logic)
│   ├── services/       # Business logic + Harness client
│   ├── queue/          # Redis/RQ connection + enqueue helpers
│   ├── workers/        # RQ job functions + worker entrypoint
│   └── utils/          # Structured logging
├── tests/              # Unit + integration tests
├── scripts/            # Smoke test, seed scripts
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Running Tests (without Docker)

```bash
pip install -r requirements.txt
pip install pytest httpx

# Unit tests (no external dependencies)
pytest tests/test_metrics.py -v

# Integration tests (SQLite in-memory)
pytest tests/test_api.py -v
```

---

## Scaling Workers

Run multiple worker containers for parallel processing:

```yaml
# docker-compose.override.yml
services:
  worker:
    deploy:
      replicas: 3
```

Or start additional workers:

```bash
docker compose up --scale worker=3
```

---

## Harness Webhook Configuration

Configure your Harness pipeline to send a POST webhook to:

```
http://your-backend-host:8000/api/events/scm
```

With payload:
```json
{
  "provider": "harness",
  "event": "pr.opened",
  "repository": "your-org/your-repo",
  "metadata": {
    "pr_number": <PR_NUMBER>
  }
}
```

The backend extracts `pr_number` from `metadata` and fetches full PR details from the Harness Code API.
