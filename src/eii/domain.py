"""Canonical, provider-independent Observatory domain model."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, NoReturn

import rfc8785

from ._version import __version__

SCHEMA_VERSION = "2.0"


class FrozenDict(dict[str, Any]):
    """A recursively frozen JSON object suitable for stable hashed values."""

    @staticmethod
    def _immutable() -> NoReturn:
        raise TypeError("hashed JSON values are immutable")

    def __setitem__(self, _key: str, _value: Any) -> None:
        self._immutable()

    def __delitem__(self, _key: str) -> None:
        self._immutable()

    def clear(self) -> None:
        self._immutable()

    def pop(self, _key: str, _default: Any = None) -> Any:
        self._immutable()

    def popitem(self) -> tuple[str, Any]:
        self._immutable()

    def setdefault(self, _key: str, _default: Any = None) -> Any:
        self._immutable()

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._immutable()

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenDict:
        return self


def freeze_json(value: Any) -> Any:
    """Validate and recursively freeze a value in the RFC 8785 data model."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return FrozenDict({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, bool, int, float)):
        # The canonicalizer rejects non-finite floats, unsafe integers, and lone surrogates.
        rfc8785.dumps(value)
        return value
    raise TypeError(f"value is not representable as canonical JSON: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize with RFC 8785 JSON Canonicalization Scheme (JCS)."""
    if is_dataclass(value):
        value = asdict(value)  # type: ignore[arg-type]
    return rfc8785.dumps(value).decode("utf-8")


def content_hash(value: Any) -> str:
    return "sha256:" + sha256(canonical_json(value).encode("utf-8")).hexdigest()


class UnitKind(StrEnum):
    COURSE = "course"
    ACTIVITY = "activity"
    SECTION = "section"
    EXERCISE = "exercise"
    ASSESSMENT = "assessment"


class FindingStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    INTENTIONAL_LOCALIZATION = "intentional_localization"
    PARTIALLY_CORRECT = "partially_correct"
    CANNOT_DETERMINE = "cannot_determine"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SourceLocator:
    adapter: str
    repository: str
    path: str
    anchor: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class ContentBlock:
    id: str
    kind: UnitKind
    title: str
    text: str
    order: int
    locator: SourceLocator
    parent_id: str | None = None
    concepts: tuple[str, ...] = ()
    learning_objectives: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        if not self.id or not self.locator.path:
            raise ValueError("content block requires id and source path")
        payload = {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "text": self.text,
            "order": self.order,
            "locator": asdict(self.locator),
            "parent_id": self.parent_id,
            "concepts": self.concepts,
            "learning_objectives": self.learning_objectives,
            "metadata": self.metadata,
        }
        expected = content_hash(payload)
        if self.hash and self.hash != expected:
            raise ValueError("content block hash does not match its canonical payload")
        object.__setattr__(self, "hash", expected)


@dataclass(frozen=True, slots=True)
class CourseRelease:
    id: str
    course_key: str
    language: str
    version: str
    title: str
    blocks: tuple[ContentBlock, ...]
    source: SourceLocator
    content_license: str | None = None
    canonical_course_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        if not self.language or not self.blocks:
            raise ValueError("course release requires language and content blocks")
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("content block ids must be unique within a release")
        payload = {
            "id": self.id,
            "course_key": self.course_key,
            "language": self.language,
            "version": self.version,
            "title": self.title,
            "block_hashes": [b.hash for b in self.blocks],
            "source": asdict(self.source),
            "content_license": self.content_license,
            "canonical_course_id": self.canonical_course_id,
            "metadata": self.metadata,
        }
        expected = content_hash(payload)
        if self.hash and self.hash != expected:
            raise ValueError("course release hash does not match its canonical payload")
        object.__setattr__(self, "hash", expected)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    course_release_id: str
    block_id: str
    block_hash: str
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRun:
    provider: str
    model: str
    prompt_version: str
    configuration: Mapping[str, Any]
    input_hash: str
    output_hash: str
    latency_ms: int | None = None
    cost: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.provider,
                self.model,
                self.prompt_version,
                self.input_hash,
                self.output_hash,
            )
        ):
            raise ValueError("model-run identity and hashes must be non-empty strings")
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ValueError("model-run latency must be a non-negative integer")
        if self.cost is not None and (
            not isinstance(self.cost, (int, float))
            or isinstance(self.cost, bool)
            or not math.isfinite(self.cost)
            or self.cost < 0
        ):
            raise ValueError("model-run cost must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    finding_type: str
    title: str
    explanation: str
    severity: Severity
    confidence: float
    evidence: tuple[EvidenceRef, ...]
    affected_languages: tuple[str, ...] = ()
    suggested_action: str | None = None
    status: FindingStatus = FindingStatus.PROPOSED
    model_run: ModelRun | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        if not 0 <= self.confidence <= 1:
            raise ValueError("finding confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    finding_id: str
    decision: FindingStatus
    reviewer: str
    rationale: str
    created_at: str
    evidence_quality: str | None = None
    severity_assessment: str | None = None
    usefulness: int | None = None
    actionability: str | None = None
    seconds_spent: int | None = None
    review_round: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    id: str
    created_at: str
    tool_version: str
    course_releases: tuple[CourseRelease, ...]
    findings: tuple[Finding, ...]
    reviews: tuple[ReviewDecision, ...] = ()
    model_runs: tuple[ModelRun, ...] = ()
    schema_version: str = SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @classmethod
    def create(
        cls, releases: tuple[CourseRelease, ...], findings: tuple[Finding, ...]
    ) -> EvidenceBundle:
        now = datetime.now(UTC).isoformat()
        runs = tuple(
            {
                content_hash(to_dict(finding.model_run)): finding.model_run
                for finding in findings
                if finding.model_run
            }.values()
        )
        bundle = cls("", now, __version__, releases, findings, model_runs=runs)
        return seal_bundle(bundle)


def to_dict(value: Any) -> Any:
    """Convert domain values into JSON-safe values without losing enum values."""
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {f.name: to_dict(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): to_dict(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_dict(v) for v in value]
    return value


def bundle_payload(bundle: EvidenceBundle) -> Mapping[str, Any]:
    """Every serialized decision-relevant field except the self-referential ID."""
    payload = to_dict(bundle)
    return {key: value for key, value in payload.items() if key != "id"}


def seal_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    """Return a bundle whose ID binds releases, findings, reviews, runs and metadata."""
    from dataclasses import replace

    return replace(bundle, id=content_hash(bundle_payload(bundle)))
