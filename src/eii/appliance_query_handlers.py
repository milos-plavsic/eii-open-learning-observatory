"""Authenticated, bounded tutor-query route for the offline appliance."""

from __future__ import annotations

import hmac
import json
import threading
from collections.abc import Callable
from typing import cast
from urllib.parse import urlparse

from .appliance_handler_support import send_json
from .appliance_types import ApplianceConfig
from .domain import CourseRelease, to_dict
from .safety_types import AssistantResponse
from .service import ObservableHandler
from .service_limits import BoundedRateLimiter
from .tutor import GroundedTutor


def capacity_answer(
    capacity: threading.BoundedSemaphore,
    tutor: GroundedTutor,
    course: CourseRelease,
    data: dict[str, object],
    behavior: str,
    language: str,
) -> AssistantResponse | None:
    if not capacity.acquire(blocking=False):
        return None
    try:
        return tutor.answer(
            f"Assistant behavior: {behavior}. {cast(str, data['question'])}",
            course=course,
            activity_id=cast(str | None, data.get("activity_id")),
            language=language,
        )
    finally:
        capacity.release()


def query_handler(
    *,
    tutor: GroundedTutor | None,
    course: CourseRelease | None,
    config: ApplianceConfig | None,
    query_token: str | None,
    rate_limiter: BoundedRateLimiter,
    capacity: threading.BoundedSemaphore,
) -> Callable[[ObservableHandler], None]:
    def query(handler: ObservableHandler) -> None:
        if tutor is None or course is None:
            handler.send_error(404)
            return
        if rate_limiter.limited(handler.client_address[0]):
            handler.send_error(429, "query rate limit exceeded")
            return
        if query_token is not None:
            authorization = handler.headers.get("Authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
            if not supplied or not hmac.compare_digest(supplied, query_token):
                handler.send_error(401, "valid classroom bearer token required")
                return
        try:
            content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValueError("Content-Type must be application/json")
            origin = handler.headers.get("Origin")
            if origin and urlparse(origin).netloc != handler.headers.get("Host"):
                raise ValueError("cross-origin requests are not allowed")
            length = int(handler.headers.get("Content-Length", "0"))
            if length < 1 or length > 32_768:
                raise ValueError("request size must be between 1 and 32768 bytes")
            data = json.loads(handler.rfile.read(length))
            if set(data) - {"question", "language", "activity_id"}:
                raise ValueError("query contains unsupported fields")
            question = data["question"]
            if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                raise ValueError("question must be a non-empty string of at most 4000 characters")
            language = data.get("language", course.language)
            if not isinstance(language, str):
                raise ValueError("language must be a string")
            if config and language not in config.allowed_languages:
                raise ValueError("requested language is not enabled by the teacher")
            response = capacity_answer(
                capacity,
                tutor,
                course,
                data,
                config.assistant_behavior if config else "hint-first",
                language,
            )
            if response is None:
                handler.send_error(503, "model query capacity exhausted")
                return
            send_json(
                handler,
                {
                    "answer": response.answer,
                    "citations": response.citations,
                    "retrieved": [
                        {
                            "block_id": item.block_id,
                            "block_hash": item.block_hash,
                            "score": item.score,
                        }
                        for item in response.retrieved
                    ],
                    "model_run": to_dict(response.model_run),
                },
                200,
            )
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            send_json(handler, {"error": str(error)}, 400)

    return query
