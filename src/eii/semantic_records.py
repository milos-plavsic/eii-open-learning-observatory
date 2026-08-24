"""Typed, versioned semantic-evaluation evidence records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .domain import EvidenceRef, ModelRun, content_hash, freeze_json, to_dict

SEMANTIC_RECORD_VERSION = "2.0"
OUTCOMES = frozenset({"equivalent", "drift", "abstained"})


def model_run_id(run: ModelRun) -> str:
    """Bind a run reference to input, output, identity, configuration, cost and latency."""
    return content_hash(to_dict(run))


@dataclass(frozen=True, slots=True)
class SemanticEvaluationRecord:
    id: str
    relationship_id: str
    left_evidence: tuple[EvidenceRef, ...]
    right_evidence: tuple[EvidenceRef, ...]
    outcome: str
    decision_score: float
    properties: Mapping[str, bool]
    explanation: str
    model_run_id: str
    member_judgments: tuple[Mapping[str, Any], ...] = ()
    decision_signals: Mapping[str, Any] = field(
        default_factory=lambda: {
            "agreement_ratio": None,
            "majority_mean_confidence": None,
            "minority_mean_confidence": None,
            "confidence_kind": "uncalibrated_member_self_report",
            "property_signals": {},
            "completion_ratio": None,
            "failed_member_count": 0,
        }
    )
    schema_version: str = SEMANTIC_RECORD_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", freeze_json(self.properties))
        object.__setattr__(self, "member_judgments", freeze_json(self.member_judgments))
        object.__setattr__(self, "decision_signals", freeze_json(self.decision_signals))
        if self.schema_version != SEMANTIC_RECORD_VERSION or self.outcome not in OUTCOMES:
            raise ValueError("unsupported semantic evaluation schema or outcome")
        if not 0 <= self.decision_score <= 1:
            raise ValueError("semantic evaluation score must be between zero and one")
        if not self.relationship_id or not self.explanation:
            raise ValueError("semantic evaluation requires relationship identity and explanation")
        payload = {key: value for key, value in to_dict(self).items() if key != "id"}
        expected = content_hash(payload)
        if self.id and self.id != expected:
            raise ValueError("semantic evaluation id does not match its canonical payload")
        object.__setattr__(self, "id", expected)


def parse_semantic_records(values: object) -> tuple[SemanticEvaluationRecord, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("semantic evaluations must be an array")
    records = []
    fields = {
        "id",
        "relationship_id",
        "left_evidence",
        "right_evidence",
        "outcome",
        "decision_score",
        "properties",
        "explanation",
        "model_run_id",
        "member_judgments",
        "decision_signals",
        "schema_version",
    }
    for value in values:
        legacy_fields = fields - {"decision_signals"}
        if not isinstance(value, Mapping) or frozenset(value) not in {
            frozenset(fields),
            frozenset(legacy_fields),
        }:
            raise ValueError("semantic evaluation fields do not match schema")
        legacy = set(value) == legacy_fields
        if legacy:
            legacy_payload = {key: item for key, item in value.items() if key != "id"}
            if value["schema_version"] != "1.0" or value["id"] != content_hash(legacy_payload):
                raise ValueError("legacy semantic evaluation id is invalid")
        left = _refs(value["left_evidence"])
        right = _refs(value["right_evidence"])
        records.append(
            SemanticEvaluationRecord(
                "" if legacy else str(value["id"]),
                str(value["relationship_id"]),
                left,
                right,
                str(value["outcome"]),
                float(value["decision_score"]),
                _bool_mapping(value["properties"]),
                str(value["explanation"]),
                str(value["model_run_id"]),
                _member_records(value["member_judgments"]),
                _decision_signals(value["decision_signals"])
                if not legacy
                else _decision_signals(
                    {
                        "agreement_ratio": None,
                        "majority_mean_confidence": float(value["decision_score"]),
                        "minority_mean_confidence": None,
                        "confidence_kind": "uncalibrated_member_self_report",
                        "property_signals": {},
                        "completion_ratio": None,
                        "failed_member_count": 0,
                    }
                ),
                SEMANTIC_RECORD_VERSION,
            )
        )
    return tuple(records)


def parse_semantic_plan(
    value: object, relationships: Mapping[str, set[tuple[str, str]]]
) -> set[tuple[str, str, str]]:
    """Validate the sealed set of relationship/release comparisons."""
    if not isinstance(value, (list, tuple)):
        raise ValueError("semantic evaluations require a sealed evaluation plan")
    plan: set[tuple[str, str, str]] = set()
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"relationship_id", "left_release_id", "right_release_id"}
            or any(not isinstance(field, str) or not field for field in item.values())
        ):
            raise ValueError("semantic evaluation plan item is invalid")
        key = (item["relationship_id"], item["left_release_id"], item["right_release_id"])
        members = relationships.get(item["relationship_id"])
        if (
            key in plan
            or item["left_release_id"] == item["right_release_id"]
            or members is None
            or not any(member[0] == item["left_release_id"] for member in members)
            or not any(member[0] == item["right_release_id"] for member in members)
        ):
            raise ValueError("semantic evaluation plan item is inconsistent")
        plan.add(key)
    return plan


def _refs(values: object) -> tuple[EvidenceRef, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("semantic evaluation evidence must be a non-empty array")
    result = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {
            "course_release_id",
            "block_id",
            "block_hash",
            "excerpt",
        }:
            raise ValueError("semantic evaluation evidence fields do not match schema")
        result.append(EvidenceRef(**value))
    return tuple(result)


def _bool_mapping(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, bool) for key, item in value.items()
    ):
        raise ValueError("semantic evaluation properties must be boolean fields")
    return dict(value)


def _member_records(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("semantic member judgments must be an array")
    records = []
    for record in value:
        if not isinstance(record, Mapping):
            raise ValueError("semantic member judgment must be an object")
        fields = set(record)
        if fields == {"member_index", "error_type"} or fields == {
            "member_index",
            "error_type",
            "message_hash",
        }:
            if (
                not isinstance(record["member_index"], int)
                or isinstance(record["member_index"], bool)
                or record["member_index"] < 0
                or not isinstance(record["error_type"], str)
                or not record["error_type"]
                or (
                    "message_hash" in record
                    and (
                        not isinstance(record["message_hash"], str)
                        or not record["message_hash"].startswith("sha256:")
                    )
                )
            ):
                raise ValueError("semantic member failure record is invalid")
        elif fields == {"equivalent", "confidence", "properties", "explanation", "model_run"}:
            if (
                not isinstance(record["equivalent"], bool)
                or not isinstance(record["confidence"], (int, float))
                or isinstance(record["confidence"], bool)
                or not 0 <= record["confidence"] <= 1
                or not isinstance(record["explanation"], str)
                or not record["explanation"]
                or not isinstance(record["model_run"], Mapping)
            ):
                raise ValueError("semantic member success record is invalid")
            _bool_mapping(record["properties"])
        else:
            raise ValueError("semantic member judgment fields do not match schema")
        records.append(dict(record))
    return tuple(records)


def _decision_signals(value: object) -> dict[str, Any]:
    required = {
        "agreement_ratio",
        "majority_mean_confidence",
        "minority_mean_confidence",
        "confidence_kind",
        "property_signals",
        "completion_ratio",
        "failed_member_count",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("semantic decision signals do not match schema")
    for name in required - {
        "confidence_kind",
        "property_signals",
        "failed_member_count",
    }:
        item = value[name]
        if item is not None and (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not 0 <= float(item) <= 1
        ):
            raise ValueError("semantic decision signal must be null or between zero and one")
    failed = value["failed_member_count"]
    if not isinstance(failed, int) or isinstance(failed, bool) or failed < 0:
        raise ValueError("semantic failed member count must be a non-negative integer")
    if value["confidence_kind"] != "uncalibrated_member_self_report":
        raise ValueError("semantic confidence kind is unsupported")
    properties = value["property_signals"]
    if not isinstance(properties, Mapping):
        raise ValueError("semantic property signals must be an object")
    signal_fields = {
        "agreement_ratio",
        "majority_mean_confidence",
        "minority_mean_confidence",
    }
    for name, signals in properties.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(signals, Mapping)
            or set(signals) != signal_fields
        ):
            raise ValueError("semantic property signal fields do not match schema")
        for item in signals.values():
            if item is not None and (
                not isinstance(item, (int, float)) or isinstance(item, bool) or not 0 <= item <= 1
            ):
                raise ValueError("semantic property signal must be null or between zero and one")
    return dict(value)
