import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .alignment_relationships import parse_sealed_relationships
from .domain import (
    ContentBlock,
    CourseRelease,
    EvidenceBundle,
    EvidenceRef,
    Finding,
    FindingStatus,
    ModelRun,
    ReviewDecision,
    Severity,
    SourceLocator,
    UnitKind,
    bundle_payload,
    content_hash,
    seal_bundle,
    to_dict,
)
from .report_evidence import ReportEvidenceParser
from .semantic_records import model_run_id, parse_semantic_plan, parse_semantic_records


def write_bundle(bundle: EvidenceBundle, destination: Path) -> None:
    bundle = seal_bundle(bundle)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(to_dict(bundle), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_audit_directory(directory: Path) -> EvidenceBundle:
    """Verify a complete audit directory against its sealed evidence manifest."""
    bundle = load_bundle(directory / "evidence.json")
    artifacts = bundle.metadata.get("audit_artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("evidence bundle has no audit artifact manifest")
    for name, filename in (
        ("alignments", "alignments.json"),
        ("translation_status", "translation-status.json"),
    ):
        record = artifacts.get(name)
        if not isinstance(record, Mapping) or set(record) != {
            "schema_version",
            "content_hash",
            "records",
        }:
            raise ValueError(f"invalid {name} artifact manifest")
        actual = json.loads((directory / filename).read_text("utf-8"))
        if record["schema_version"] != "1.0" or to_dict(record["records"]) != actual:
            raise ValueError(f"{name} artifact does not match sealed evidence")
        if record["content_hash"] != content_hash(actual):
            raise ValueError(f"{name} artifact hash does not match sealed evidence")
    parser = ReportEvidenceParser()
    parser.feed((directory / "index.html").read_text("utf-8"))
    if parser.payload is None:
        raise ValueError("audit report has no embedded evidence payload")
    embedded = json.loads(parser.payload.replace("<\\/", "</"))
    if not isinstance(embedded, dict) or embedded.get("bundle") != to_dict(bundle):
        raise ValueError("audit report bundle does not match sealed evidence")
    if embedded.get("alignments") != to_dict(artifacts["alignments"]["records"]):
        raise ValueError("audit report alignments do not match sealed evidence")
    return bundle


def _exact(value: object, fields: set[str], kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{kind} fields do not match schema")
    return cast(dict[str, Any], value)


def _locator(value: object) -> SourceLocator:
    data = _exact(value, {"adapter", "repository", "path", "anchor", "source_url"}, "locator")
    return SourceLocator(**data)


def _model_run(value: object) -> ModelRun:
    data = _exact(
        value,
        {
            "provider",
            "model",
            "prompt_version",
            "configuration",
            "input_hash",
            "output_hash",
            "latency_ms",
            "cost",
        },
        "model run",
    )
    return ModelRun(**data)


def load_bundle(path: Path) -> EvidenceBundle:
    """Deserialize and recompute all nested hashes and cross-references."""
    raw = json.loads(path.read_text("utf-8"))
    data = _exact(
        raw,
        {
            "id",
            "created_at",
            "tool_version",
            "course_releases",
            "findings",
            "reviews",
            "model_runs",
            "schema_version",
            "metadata",
        },
        "evidence bundle",
    )
    releases = []
    for release_value in data["course_releases"]:
        release_data = _exact(
            release_value,
            {
                "id",
                "course_key",
                "language",
                "version",
                "title",
                "blocks",
                "source",
                "content_license",
                "canonical_course_id",
                "metadata",
                "hash",
            },
            "course release",
        )
        blocks = []
        for block_value in release_data["blocks"]:
            block = _exact(
                block_value,
                {
                    "id",
                    "kind",
                    "title",
                    "text",
                    "order",
                    "locator",
                    "parent_id",
                    "concepts",
                    "learning_objectives",
                    "metadata",
                    "hash",
                },
                "content block",
            )
            blocks.append(
                ContentBlock(
                    block["id"],
                    UnitKind(block["kind"]),
                    block["title"],
                    block["text"],
                    block["order"],
                    _locator(block["locator"]),
                    block["parent_id"],
                    tuple(block["concepts"]),
                    tuple(block["learning_objectives"]),
                    block["metadata"],
                    block["hash"],
                )
            )
        releases.append(
            CourseRelease(
                release_data["id"],
                release_data["course_key"],
                release_data["language"],
                release_data["version"],
                release_data["title"],
                tuple(blocks),
                _locator(release_data["source"]),
                release_data["content_license"],
                release_data["canonical_course_id"],
                release_data["metadata"],
                release_data["hash"],
            )
        )
    findings = []
    for finding_value in data["findings"]:
        finding_data = _exact(
            finding_value,
            {
                "id",
                "finding_type",
                "title",
                "explanation",
                "severity",
                "confidence",
                "evidence",
                "affected_languages",
                "suggested_action",
                "status",
                "model_run",
                "metadata",
            },
            "finding",
        )
        refs = tuple(
            EvidenceRef(
                **_exact(
                    item,
                    {"course_release_id", "block_id", "block_hash", "excerpt"},
                    "evidence reference",
                )
            )
            for item in finding_data["evidence"]
        )
        run = (
            _model_run(finding_data["model_run"]) if finding_data["model_run"] is not None else None
        )
        findings.append(
            Finding(
                finding_data["id"],
                finding_data["finding_type"],
                finding_data["title"],
                finding_data["explanation"],
                Severity(finding_data["severity"]),
                finding_data["confidence"],
                refs,
                tuple(finding_data["affected_languages"]),
                finding_data["suggested_action"],
                FindingStatus(finding_data["status"]),
                run,
                finding_data["metadata"],
            )
        )
    review_fields = {
        "finding_id",
        "decision",
        "reviewer",
        "rationale",
        "created_at",
        "evidence_quality",
        "severity_assessment",
        "usefulness",
        "actionability",
        "seconds_spent",
        "review_round",
    }
    reviews = tuple(
        ReviewDecision(**{**review, "decision": FindingStatus(review["decision"])})
        for value in data["reviews"]
        for review in [_exact(value, review_fields, "review")]
    )
    model_runs = tuple(_model_run(value) for value in data["model_runs"])
    bundle = EvidenceBundle(
        data["id"],
        data["created_at"],
        data["tool_version"],
        tuple(releases),
        tuple(findings),
        reviews,
        model_runs,
        data["schema_version"],
        data["metadata"],
    )
    release_blocks = {
        (release.id, block.id): block for release in releases for block in release.blocks
    }
    for finding in findings:
        for reference in finding.evidence:
            actual_block = release_blocks.get((reference.course_release_id, reference.block_id))
            if actual_block is None or actual_block.hash != reference.block_hash:
                raise ValueError(f"finding {finding.id} contains an invalid evidence reference")
            if reference.excerpt != (actual_block.text[:240] or None):
                raise ValueError(f"finding {finding.id} contains a non-canonical evidence excerpt")
    known_runs = {model_run_id(run) for run in model_runs}
    if any(
        finding.model_run is not None and model_run_id(finding.model_run) not in known_runs
        for finding in findings
    ):
        raise ValueError("finding refers to a model run absent from the bundle run registry")
    finding_ids = {finding.id for finding in findings}
    if any(review.finding_id not in finding_ids for review in reviews):
        raise ValueError("review refers to an unknown finding")
    if data["schema_version"] not in {"1.0", "2.0"} or data["id"] != content_hash(
        bundle_payload(bundle)
    ):
        raise ValueError("evidence bundle schema or canonical id is invalid")
    _validate_semantic_graph(bundle, release_blocks)
    return bundle


def _validate_semantic_graph(
    bundle: EvidenceBundle, release_blocks: Mapping[tuple[str, str], ContentBlock]
) -> None:
    metadata = bundle.metadata
    has_semantics = (
        "semantic_evaluations" in metadata
        or "semantic_evaluations_schema_version" in metadata
        or "semantic_evaluation_plan" in metadata
    )
    if not has_semantics:
        return
    schema_version = metadata.get("semantic_evaluations_schema_version")
    if schema_version not in {"1.0", "2.0"}:
        raise ValueError("evidence bundle has no supported semantic evaluation schema")
    serialized_records = metadata.get("semantic_evaluations")
    if not isinstance(serialized_records, (list, tuple)) or any(
        not isinstance(record, Mapping) or record.get("schema_version") != schema_version
        for record in serialized_records
    ):
        raise ValueError("semantic evaluation records do not match their declared schema")
    records = parse_semantic_records(serialized_records)
    if len({record.id for record in records}) != len(records):
        raise ValueError("semantic evaluation identifiers must be unique")
    runs = {model_run_id(run): run for run in bundle.model_runs}
    artifacts = metadata.get("audit_artifacts")
    alignments = artifacts.get("alignments") if isinstance(artifacts, Mapping) else None
    alignment_records = alignments.get("records") if isinstance(alignments, Mapping) else None
    relationships = parse_sealed_relationships(alignment_records, release_blocks)
    plan = parse_semantic_plan(metadata.get("semantic_evaluation_plan"), relationships)
    semantic_findings = [
        finding
        for finding in bundle.findings
        if finding.model_run is not None
        and finding.finding_type.startswith("translation.semantic_")
    ]
    completed: set[tuple[str, str, str]] = set()
    for record in records:
        run = runs.get(record.model_run_id)
        if run is None:
            raise ValueError("semantic evaluation refers to an unknown model run")
        members = relationships.get(record.relationship_id)
        if members is None:
            raise ValueError("semantic evaluation refers to an unknown alignment relationship")
        left_releases = {reference.course_release_id for reference in record.left_evidence}
        right_releases = {reference.course_release_id for reference in record.right_evidence}
        if len(left_releases) != 1 or len(right_releases) != 1 or left_releases == right_releases:
            raise ValueError("semantic evaluation sides must identify two distinct releases")
        comparison = (
            record.relationship_id,
            next(iter(left_releases)),
            next(iter(right_releases)),
        )
        if comparison in completed:
            raise ValueError("semantic evaluation plan item has multiple results")
        completed.add(comparison)
        for reference in (*record.left_evidence, *record.right_evidence):
            block = release_blocks.get((reference.course_release_id, reference.block_id))
            if block is None or block.hash != reference.block_hash:
                raise ValueError("semantic evaluation contains an invalid evidence reference")
            if reference.excerpt != (block.text[:240] or None):
                raise ValueError("semantic evaluation contains a non-canonical evidence excerpt")
            if (reference.course_release_id, reference.block_id) not in members:
                raise ValueError(
                    "semantic evaluation evidence is outside its alignment relationship"
                )
        configured_members = tuple(run.configuration.get("member_judgments", ()))
        configured_failures = tuple(run.configuration.get("failures", ()))
        if record.member_judgments != configured_members + configured_failures:
            raise ValueError("semantic evaluation member judgments disagree with its model run")
        if record.outcome in {"equivalent", "drift"} and not record.properties:
            raise ValueError("decisive semantic evaluations require property judgments")
        if record.outcome == "equivalent" and not all(record.properties.values()):
            raise ValueError("equivalent semantic evaluations require all properties to pass")
        if record.outcome == "drift" and all(record.properties.values()):
            raise ValueError("semantic drift requires at least one failed property")
        expected_finding = {
            "drift": "translation.semantic_drift",
            "abstained": "translation.semantic_uncertain",
        }.get(record.outcome)
        expected_evidence = {*record.left_evidence, *record.right_evidence}
        matching_findings = [
            finding
            for finding in semantic_findings
            if finding.model_run is not None
            and model_run_id(finding.model_run) == record.model_run_id
            and finding.finding_type == expected_finding
            and set(finding.evidence) == expected_evidence
        ]
        if (expected_finding is None and matching_findings) or (
            expected_finding is not None and len(matching_findings) != 1
        ):
            raise ValueError("semantic evaluation outcome disagrees with its finding projection")
    if completed != plan:
        raise ValueError("semantic evaluation results do not exactly satisfy the sealed plan")
