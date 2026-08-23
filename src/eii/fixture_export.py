"""Turn evidence-backed gaps into permanent Tutor Safety Case fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from .domain import Finding


def export_findings_as_suite(
    findings: tuple[Finding, ...], destination: Path, *, version: str
) -> None:
    fixtures = []
    for finding in findings:
        question = finding.metadata.get("test_question")
        if not question:
            continue
        expected = finding.metadata.get("expected_block_ids", ())
        fixtures.append(
            {
                "id": f"regression:{finding.id}",
                "claim": "course-groundedness",
                "question": question,
                "language": finding.affected_languages[0] if finding.affected_languages else "en",
                "activity_id": None,
                "properties": {"citations_required": True, "expected_citation_ids": list(expected)},
            }
        )
    payload = {
        "version": version,
        "fixtures": fixtures,
        "gates": [{"claim": "course-groundedness", "required_pass_rate": 1.0}] if fixtures else [],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def export_finding_regressions(
    findings: tuple[Finding, ...], destination: Path, *, version: str
) -> None:
    cases = []
    for finding in findings:
        cases.append(
            {
                "id": f"finding:{finding.id}",
                "finding_type": finding.finding_type,
                "title": finding.title,
                "evidence": [
                    {"block_id": ref.block_id, "block_hash": ref.block_hash}
                    for ref in finding.evidence
                ],
                "affected_languages": list(finding.affected_languages),
                "reproduction": {"expected_present": True, "source_bundle_version": version},
            }
        )
    payload = {"schema_version": "1.0", "version": version, "cases": cases}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def verify_finding_regressions(cases_path: Path, evidence_path: Path) -> dict[str, object]:
    cases = json.loads(cases_path.read_text("utf-8"))["cases"]
    findings = json.loads(evidence_path.read_text("utf-8"))["findings"]
    active = {
        (item["finding_type"], tuple(sorted(ref["block_id"] for ref in item.get("evidence", ()))))
        for item in findings
    }
    results = []
    for case in cases:
        key = (
            case["finding_type"],
            tuple(sorted(ref["block_id"] for ref in case.get("evidence", ()))),
        )
        present = key in active
        results.append(
            {
                "id": case["id"],
                "status": "still_present" if present else "resolved",
                "finding_type": case["finding_type"],
            }
        )
    return {
        "schema_version": "1.0",
        "results": results,
        "still_present": sum(item["status"] == "still_present" for item in results),
        "resolved": sum(item["status"] == "resolved" for item in results),
    }
