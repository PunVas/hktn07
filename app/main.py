"""
PR Guardian — FastAPI application entry point.

Startup sequence:
1. Configure structured logging.
2. Create all DB tables (no Alembic).
3. Mount all API routers under /api prefix.
4. Register request_id middleware.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.pr import router as pr_router
from app.config.settings import get_settings
from app.db.session import init_db
from app.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info("PR Guardian starting up")
    init_db()
    logger.info("PR Guardian ready to serve requests")
    yield
    logger.info("PR Guardian shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PR Guardian",
        description=(
            "Backend API for PR Guardian — continuous PR health analysis. "
            "Processes Harness SCM events asynchronously and serves metrics "
            "to the Chrome Extension."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---------------------------------------------------------------------------
    # CORS middleware — allow Chrome Extension and local dev
    # ---------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"chrome-extension://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Request ID middleware
    # ---------------------------------------------------------------------------
    @app.middleware("http")
    async def add_request_id(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        start = time.monotonic()

        response: Response = await call_next(request)

        duration_ms = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        logger.info(
            "Request processed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    # ---------------------------------------------------------------------------
    # Global exception handler — never leak stack traces to clients
    # ---------------------------------------------------------------------------
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled exception",
            extra={"request_id": request_id, "error": str(exc)},
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    app.include_router(health_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(pr_router, prefix="/api")

    return app


app = create_app()
