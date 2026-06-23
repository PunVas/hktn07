"""API package"""
from app.api.events import router as events_router
from app.api.pr import router as pr_router
from app.api.health import router as health_router

__all__ = ["events_router", "pr_router", "health_router"]
