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
    agreement_ratio: float | None = None
    majority_mean_confidence: float | None = None
    minority_mean_confidence: float | None = None
    property_signals: Mapping[str, Mapping[str, float | None]] | None = None
    completion_ratio: float | None = None
    failed_member_count: int = 0


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
