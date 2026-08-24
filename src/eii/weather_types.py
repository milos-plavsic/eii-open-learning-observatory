"""Validated minimized event and aggregate types for Classroom Weather."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class Signal(StrEnum):
    MISCONCEPTION = "misconception"
    REPEATED_QUESTION = "repeated_question"
    COMPLETE_ANSWER_REQUEST = "complete_answer_request"
    FRUSTRATION = "frustration"
    ABANDONMENT = "abandonment"
    RETRIEVAL_FAILURE = "retrieval_failure"
    UNSUPPORTED_QUESTION = "unsupported_question"


@dataclass(frozen=True, slots=True)
class MinimizedEvent:
    occurred_at: str
    course_key: str
    activity_key: str
    language: str
    concept_id: str
    signal: Signal
    contribution_token: str

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("course_key", self.course_key, 200),
            ("activity_key", self.activity_key, 200),
            ("language", self.language, 35),
            ("concept_id", self.concept_id, 200),
        ):
            if not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
                raise ValueError(f"{label} must be non-empty, bounded text without controls")
        if (
            "@" in self.contribution_token
            or len(self.contribution_token) > 128
            or any(char.isspace() or ord(char) < 33 for char in self.contribution_token)
        ):
            raise ValueError("contribution token must be pseudonymous and bounded")
        if not self.contribution_token.strip():
            raise ValueError("contribution token cannot be empty")
        occurred = datetime.fromisoformat(self.occurred_at)
        if occurred.tzinfo is None:
            raise ValueError("event timestamp must include a timezone")


@dataclass(frozen=True, slots=True)
class WeatherCell:
    course_key: str
    activity_key: str
    language: str
    concept_id: str
    signal: Signal
    event_count: int
    contributor_count: int
    explanation: str
    recommendation: str


def load_events(path: Path) -> tuple[MinimizedEvent, ...]:
    data = json.loads(path.read_text("utf-8"))
    allowed = {
        "occurred_at",
        "course_key",
        "activity_key",
        "language",
        "concept_id",
        "signal",
        "contribution_token",
    }
    events = []
    for index, item in enumerate(data["events"]):
        unexpected = set(item) - allowed
        if unexpected:
            raise ValueError(
                f"event {index} contains prohibited/unrecognized fields: {sorted(unexpected)}"
            )
        events.append(
            MinimizedEvent(
                signal=Signal(item["signal"]), **{k: v for k, v in item.items() if k != "signal"}
            )
        )
    return tuple(events)
