"""Provider-independent Tutor Safety Case value types and protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .domain import CourseRelease, ModelRun


@dataclass(frozen=True, slots=True)
class RetrievedEvidence:
    block_id: str
    block_hash: str
    text: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class AssistantResponse:
    answer: str
    citations: tuple[str, ...]
    retrieved: tuple[RetrievedEvidence, ...]
    model_run: ModelRun


class AssistantUnderTest(Protocol):
    def answer(
        self, question: str, *, course: CourseRelease, activity_id: str | None, language: str
    ) -> AssistantResponse:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SafetyFixture:
    id: str
    claim: str
    question: str
    language: str
    activity_id: str | None
    properties: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    evaluator: str
    passed: bool
    explanation: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CaseResult:
    fixture: SafetyFixture
    response: AssistantResponse
    evaluations: tuple[EvaluationResult, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    claim: str
    required_pass_rate: float
    minimum_cases: int = 1


@dataclass(frozen=True, slots=True)
class HumanEvaluation:
    fixture_id: str
    subject_hash: str
    reviewer: str
    approved: bool
    rationale: str
    created_at: str
    reviewer_public_key: str
    reviewer_key_fingerprint: str
    signature: str


@dataclass(frozen=True, slots=True)
class SafetyCase:
    id: str
    schema_version: str
    created_at: str
    course_id: str
    course_hash: str
    dataset_version: str
    prompt_version: str
    evaluator_id: str
    evaluator_version: str
    evaluator_ruleset_hash: str
    cases: tuple[CaseResult, ...]
    gates: tuple[ReleaseGate, ...]
    gate_results: Mapping[str, bool]
    release_decision: str
    known_limitations: tuple[str, ...]
    manifest_digest: str
    human_evaluations: tuple[HumanEvaluation, ...] = ()
    signature: str | None = None
