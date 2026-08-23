"""Append-only human decisions; machine findings are never overwritten."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .domain import FindingStatus, ReviewDecision


def append_review(path: Path, decision: ReviewDecision) -> None:
    if decision.decision not in {
        FindingStatus.CONFIRMED,
        FindingStatus.REJECTED,
        FindingStatus.RESOLVED,
        FindingStatus.INTENTIONAL_LOCALIZATION,
        FindingStatus.PARTIALLY_CORRECT,
        FindingStatus.CANNOT_DETERMINE,
    }:
        raise ValueError("unsupported human review decision")
    if decision.evidence_quality not in {None, "sufficient", "incomplete", "wrong", "absent"}:
        raise ValueError("unsupported evidence-quality label")
    if decision.severity_assessment not in {None, "info", "low", "medium", "high", "critical"}:
        raise ValueError("unsupported severity assessment")
    if decision.usefulness is not None and not 1 <= decision.usefulness <= 5:
        raise ValueError("usefulness must be between 1 and 5")
    if decision.actionability not in {None, "usable", "needs_revision", "unusable"}:
        raise ValueError("unsupported actionability label")
    if decision.seconds_spent is not None and decision.seconds_spent < 0:
        raise ValueError("seconds spent cannot be negative")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(decision), ensure_ascii=False, default=str) + "\n")


def read_reviews(path: Path) -> tuple[ReviewDecision, ...]:
    if not path.exists():
        return ()
    decisions = []
    for line in path.read_text("utf-8").splitlines():
        data = json.loads(line)
        data["decision"] = FindingStatus(data["decision"])
        decisions.append(ReviewDecision(**data))
    return tuple(decisions)
