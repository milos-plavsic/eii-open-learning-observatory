"""Safety-bounded tutor HTTP route group for the offline appliance."""

from __future__ import annotations

import threading

from .appliance_query_handlers import capacity_answer, query_handler
from .appliance_router import ApplianceRouter
from .appliance_types import ApplianceConfig
from .domain import CourseRelease
from .service_limits import BoundedRateLimiter
from .tutor import GroundedTutor

__all__ = ["capacity_answer", "query_handler", "register_safety_routes"]


def register_safety_routes(
    router: ApplianceRouter,
    *,
    tutor: GroundedTutor | None,
    course: CourseRelease | None,
    config: ApplianceConfig | None,
    query_token: str | None,
    rate_limiter: BoundedRateLimiter,
    capacity: threading.BoundedSemaphore,
) -> None:
    """Register the authenticated tutor route as one owned safety group."""
    router.add(
        "POST",
        "/api/query",
        query_handler(
            tutor=tutor,
            course=course,
            config=config,
            query_token=query_token,
            rate_limiter=rate_limiter,
            capacity=capacity,
        ),
    )
