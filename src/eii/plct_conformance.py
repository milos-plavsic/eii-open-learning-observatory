"""Conformance evidence for the replaceable PLCT export and retrieval boundary."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters import PlctExportAdapter
from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519
from .domain import content_hash


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PlctConformanceReport:
    schema_version: str
    export_hash: str
    course_release_id: str | None
    course_release_hash: str | None
    checks: tuple[ConformanceCheck, ...]
    compatible: bool
    external_attestation: Mapping[str, Any] | None


def evaluate_plct_export(source: Path) -> PlctConformanceReport:
    raw = source.read_bytes()
    export_hash = "sha256:" + __import__("hashlib").sha256(raw).hexdigest()
    checks: list[ConformanceCheck] = []
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("export root must be an object")
        release = PlctExportAdapter().load(source)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        checks.append(ConformanceCheck("canonical-export", False, str(error)))
        return PlctConformanceReport("1.0", export_hash, None, None, tuple(checks), False, None)
    checks.append(
        ConformanceCheck(
            "canonical-export",
            True,
            f"Loaded {len(release.blocks)} canonical blocks for {release.course_key}@{release.version}.",
        )
    )
    block_by_id = {block.id: block for block in release.blocks}
    activity_keys = {str(item["activity_key"]) for item in document["activities"]}
    stable = all(
        block.locator.path in activity_keys and block.id.startswith(f"plct:{release.course_key}:")
        for block in release.blocks
    )
    checks.append(
        ConformanceCheck(
            "stable-identifiers",
            stable,
            "Every canonical block retains its course/activity namespace."
            if stable
            else "One or more blocks lost their course/activity namespace.",
        )
    )

    cases = document.get("query_context_cases")
    if not isinstance(cases, list) or not cases:
        checks.append(
            ConformanceCheck(
                "query-context-fixtures",
                False,
                "At least one captured QueryContext case is required for integration conformance.",
            )
        )
    else:
        errors: list[str] = []
        case_ids: set[str] = set()
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.append(f"case {index} is not an object")
                continue
            case_id = str(case.get("id", "")).strip()
            if not case_id or case_id in case_ids:
                errors.append(f"case {index} id is empty or duplicated")
            case_ids.add(case_id)
            if (
                not str(case.get("question", "")).strip()
                or str(case.get("activity_key", "")) not in activity_keys
            ):
                errors.append(f"case {case_id or index} has an invalid question or activity_key")
            retrieved = case.get("retrieved")
            if not isinstance(retrieved, list) or not retrieved:
                errors.append(f"case {case_id or index} has no retrieved evidence")
                continue
            for rank, item in enumerate(retrieved, 1):
                if not isinstance(item, dict):
                    errors.append(f"case {case_id or index} retrieval {rank} is not an object")
                    continue
                block = block_by_id.get(str(item.get("block_id", "")))
                score = item.get("score")
                if block is None or item.get("block_hash") != block.hash:
                    errors.append(
                        f"case {case_id or index} retrieval {rank} is not bound to a canonical block"
                    )
                if (
                    not isinstance(score, (int, float))
                    or isinstance(score, bool)
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                ):
                    errors.append(f"case {case_id or index} retrieval {rank} has an invalid score")
        checks.append(
            ConformanceCheck(
                "query-context-fixtures",
                not errors,
                "Captured retrieval evidence is canonical and bounded."
                if not errors
                else "; ".join(errors),
            )
        )
    attestation = document.get("petlja_attestation")
    attested = (
        isinstance(attestation, dict)
        and bool(attestation.get("maintainer"))
        and bool(attestation.get("reviewed_at"))
    )
    checks.append(
        ConformanceCheck(
            "petlja-attestation",
            attested,
            "Petlja maintainer attestation is present."
            if attested
            else "No Petlja maintainer attestation is present.",
        )
    )
    compatible = all(check.passed for check in checks if check.name != "petlja-attestation")
    return PlctConformanceReport(
        "1.0",
        export_hash,
        release.id,
        release.hash,
        tuple(checks),
        compatible,
        attestation if attested else None,
    )


def compare_plct_exports(previous: Path, current: Path) -> Mapping[str, Any]:
    adapter = PlctExportAdapter()
    before = adapter.load(previous)
    after = adapter.load(current)
    if before.canonical_course_id != after.canonical_course_id:
        raise ValueError("exports do not describe the same canonical course")
    old = {block.id: block.hash for block in before.blocks}
    new = {block.id: block.hash for block in after.blocks}
    return {
        "schema_version": "1.0",
        "canonical_course_id": before.canonical_course_id,
        "previous_release": before.id,
        "current_release": after.id,
        "stable_ids": sorted(old.keys() & new.keys()),
        "added_ids": sorted(new.keys() - old.keys()),
        "removed_ids": sorted(old.keys() - new.keys()),
        "changed_ids": sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
    }


def write_conformance_report(report: PlctConformanceReport, destination: Path) -> None:
    payload = asdict(report)
    payload["report_hash"] = content_hash(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def create_conformance_attestation(
    report_path: Path,
    destination: Path,
    *,
    maintainer: str,
    repository_revision: str,
    private_key: Path,
    public_key: Path,
    organization: str = "Petlja",
) -> Mapping[str, Any]:
    report = json.loads(report_path.read_text("utf-8"))
    report_hash = str(report.pop("report_hash", ""))
    if report_hash != content_hash(report):
        raise ValueError("conformance report hash is invalid")
    if not report.get("compatible") or not report.get("course_release_hash"):
        raise ValueError("only a compatible canonical report can be attested")
    if not maintainer.strip() or not repository_revision.strip():
        raise ValueError("maintainer and repository revision are required")
    statement = {
        "schema_version": "1.0",
        "organization": organization,
        "maintainer": maintainer,
        "repository_revision": repository_revision,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "report_hash": report_hash,
        "export_hash": report["export_hash"],
        "course_release_hash": report["course_release_hash"],
    }
    body = json.dumps(statement, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    signature = sign_ed25519(body, private_key)
    if not verify_ed25519(body, signature, public_key):
        raise ValueError("attestation private and public keys do not match")
    document = {
        "id": content_hash(statement),
        "statement": statement,
        "key_fingerprint": public_key_fingerprint(public_key),
        "signature": signature,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return document


def verify_conformance_attestation(
    attestation_path: Path, report_path: Path, public_key: Path
) -> None:
    document = json.loads(attestation_path.read_text("utf-8"))
    statement = document["statement"]
    report = json.loads(report_path.read_text("utf-8"))
    report_hash = str(report.pop("report_hash", ""))
    if report_hash != content_hash(report) or statement.get("report_hash") != report_hash:
        raise ValueError("attestation is not bound to this valid conformance report")
    if document.get("id") != content_hash(statement):
        raise ValueError("attestation id is invalid")
    fingerprint = document.get("key_fingerprint")
    if fingerprint != public_key_fingerprint(public_key):
        raise ValueError("attestation key fingerprint does not match")
    body = json.dumps(statement, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if not verify_ed25519(body, str(document.get("signature", "")), public_key):
        raise ValueError("attestation signature verification failed")
