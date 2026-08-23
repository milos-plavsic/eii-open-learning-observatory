"""Provider-neutral semantic comparison contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .domain import ContentBlock, ModelRun


@dataclass(frozen=True, slots=True)
class SemanticJudgment:
    equivalent: bool
    confidence: float
    explanation: str
    properties: Mapping[str, bool]
    model_run: ModelRun
    abstained: bool = False
    member_judgments: tuple[Mapping[str, object], ...] = ()


class SemanticComparator(Protocol):
    """Implementations may call hosted APIs or local OpenAI-compatible vLLM."""

    def compare(
        self,
        left: ContentBlock,
        right: ContentBlock,
        *,
        left_language: str,
        right_language: str,
        timeout_seconds: float | None = None,
    ) -> SemanticJudgment:
        raise NotImplementedError
