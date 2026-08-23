"""Model-assisted BabelBridge findings with an explicit abstention boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from .domain import ContentBlock, CourseRelease, EvidenceRef, Finding, ModelRun, Severity
from .semantic_records import SemanticEvaluationRecord, model_run_id
from .semantics import SemanticComparator

CourseBlock = tuple[CourseRelease, ContentBlock]
FindingFactory = Callable[
    [str, str, str, Severity, float, Sequence[CourseBlock], tuple[str, ...], str], Finding
]


def semantic_findings(
    comparison_group: Sequence[CourseBlock],
    evidence_group: Sequence[CourseBlock],
    relationship_id: str,
    comparator: SemanticComparator,
    threshold: float,
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
            if judgment.abstained or judgment.confidence < threshold
            else "equivalent"
            if judgment.equivalent
            else "drift"
        )
        left_evidence = _release_refs(evidence_group, base_release.id)
        right_evidence = _release_refs(evidence_group, release.id)
        evaluations.append(
            SemanticEvaluationRecord(
                "",
                relationship_id,
                left_evidence,
                right_evidence,
                outcome,
                judgment.confidence,
                dict(judgment.properties),
                judgment.explanation,
                model_run_id(judgment.model_run),
                judgment.member_judgments,
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
