"""Model-assisted BabelBridge findings with an explicit abstention boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .domain import ContentBlock, CourseRelease, EvidenceRef, Finding, ModelRun, Severity
from .semantic_records import SemanticEvaluationRecord, model_run_id
from .semantics import SemanticComparator

CourseBlock = tuple[CourseRelease, ContentBlock]
FindingFactory = Callable[
    [str, str, str, Severity, float, Sequence[CourseBlock], tuple[str, ...], str], Finding
]


def evidence_refs(group: Sequence[CourseBlock]) -> tuple[EvidenceRef, ...]:
    return tuple(EvidenceRef(r.id, b.id, b.hash, b.text[:240] or None) for r, b in group)


@dataclass(frozen=True, slots=True)
class SemanticReleasePolicy:
    confidence: float
    agreement: float
    maximum_minority_confidence: float | None
    require_unanimity: bool
    maximum_failed_members: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1 or not 0.5 <= self.agreement <= 1:
            raise ValueError("semantic confidence and agreement must be between zero and one")
        if (
            self.maximum_minority_confidence is not None
            and not 0 <= self.maximum_minority_confidence <= 1
        ):
            raise ValueError("semantic maximum minority confidence must be between zero and one")
        if isinstance(self.maximum_failed_members, bool) or self.maximum_failed_members < 0:
            raise ValueError("semantic maximum failed members must be a non-negative integer")


def semantic_findings(
    comparison_group: Sequence[CourseBlock],
    evidence_group: Sequence[CourseBlock],
    relationship_id: str,
    comparator: SemanticComparator,
    threshold: float,
    minimum_agreement: float,
    maximum_minority_confidence: float | None,
    require_unanimity: bool,
    maximum_failed_members: int,
    finding: FindingFactory,
) -> tuple[list[Finding], list[ModelRun], list[SemanticEvaluationRecord]]:
    base_release, base_block = comparison_group[0]
    findings = []
    runs = []
    evaluations: list[SemanticEvaluationRecord] = []
    for release, block in comparison_group[1:]:
        judgment = comparator.compare(
            base_block, block, left_language=base_release.language, right_language=release.language
        )
        runs.append(judgment.model_run)
        outcome = (
            "abstained"
            if judgment.abstained
            or judgment.confidence < threshold
            or (
                judgment.agreement_ratio is not None
                and (
                    judgment.agreement_ratio < minimum_agreement
                    or (require_unanimity and judgment.agreement_ratio < 1)
                )
            )
            or (
                maximum_minority_confidence is not None
                and judgment.minority_mean_confidence is not None
                and judgment.minority_mean_confidence > maximum_minority_confidence
            )
            or judgment.failed_member_count > maximum_failed_members
            else "equivalent"
            if judgment.equivalent
            else "drift"
        )
        left_evidence = _release_refs(evidence_group, base_release.id)
        right_evidence = _release_refs(evidence_group, release.id)
        evaluations.append(
            SemanticEvaluationRecord(
                id="",
                relationship_id=relationship_id,
                left_evidence=left_evidence,
                right_evidence=right_evidence,
                outcome=outcome,
                decision_score=judgment.confidence,
                properties=dict(judgment.properties),
                explanation=judgment.explanation,
                model_run_id=model_run_id(judgment.model_run),
                member_judgments=judgment.member_judgments,
                decision_signals={
                    "agreement_ratio": judgment.agreement_ratio,
                    "majority_mean_confidence": judgment.majority_mean_confidence
                    if judgment.majority_mean_confidence is not None
                    else judgment.confidence,
                    "minority_mean_confidence": judgment.minority_mean_confidence,
                    "confidence_kind": "uncalibrated_member_self_report",
                    "property_signals": judgment.property_signals
                    or {
                        name: {
                            "agreement_ratio": None,
                            "majority_mean_confidence": None,
                            "minority_mean_confidence": None,
                        }
                        for name in sorted(judgment.properties)
                    },
                    "completion_ratio": judgment.completion_ratio,
                    "failed_member_count": judgment.failed_member_count,
                },
            )
        )
        if outcome == "abstained":
            kind, title, severity, action = (
                "translation.semantic_uncertain",
                f"Semantic comparison abstained for {release.language}",
                Severity.MEDIUM,
                "Request bilingual review; the evaluator did not meet the decision threshold.",
            )
        elif outcome == "drift":
            kind, title, severity, action = (
                "translation.semantic_drift",
                f"Possible meaning drift in {release.language}",
                Severity.HIGH,
                "Request bilingual educational review.",
            )
        else:
            continue
        proposed = finding(
            kind,
            title,
            judgment.explanation,
            severity,
            judgment.confidence,
            tuple(evidence_group),
            (base_release.language, release.language),
            action,
        )
        findings.append(replace(proposed, model_run=judgment.model_run))
    return findings, runs, evaluations


def _release_refs(group: Sequence[CourseBlock], release_id: str) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(release.id, block.id, block.hash, block.text[:240] or None)
        for release, block in group
        if release.id == release_id
    )
