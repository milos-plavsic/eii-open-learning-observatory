"""Validation, authentication, and authorization for Tutor Safety Cases."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .crypto import sign_ed25519, verify_ed25519
from .domain import CourseRelease, ModelRun, content_hash, to_dict
from .safety import SafetyEvaluator, retrieval_integrity_evaluation
from .safety_reviews import verify_human_review
from .safety_types import AssistantResponse, RetrievedEvidence, SafetyFixture


def _require_current_evaluator(document: Mapping[str, Any]) -> None:
    expected = (
        SafetyEvaluator.EVALUATOR_ID,
        SafetyEvaluator.EVALUATOR_VERSION,
        SafetyEvaluator.ruleset_hash(),
    )
    actual = tuple(
        document.get(key) for key in ("evaluator_id", "evaluator_version", "evaluator_ruleset_hash")
    )
    if actual != expected:
        raise ValueError("safety case evaluator identity does not match this verifier")


def safety_case_payload(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical, signed portion of a serialized safety case."""
    return {
        "schema_version": document["schema_version"],
        "created_at": document["created_at"],
        "course_id": document["course_id"],
        "course_hash": document["course_hash"],
        "dataset_version": document["dataset_version"],
        "prompt_version": document["prompt_version"],
        "evaluator_id": document["evaluator_id"],
        "evaluator_version": document["evaluator_version"],
        "evaluator_ruleset_hash": document["evaluator_ruleset_hash"],
        "cases": document["cases"],
        "gates": document["gates"],
        "gate_results": document["gate_results"],
        "release_decision": document["release_decision"],
        "limitations": document.get("known_limitations", []),
        "human_evaluations": document.get("human_evaluations", []),
    }


def _authenticated_model_run(response: Mapping[str, Any], fixture_id: object) -> Mapping[str, Any]:
    model_run = response.get("model_run", {})
    if not isinstance(model_run, Mapping):
        raise ValueError("model run must be an object")
    if model_run.get("output_hash") != content_hash(response.get("answer", "")):
        raise ValueError(f"answer output hash mismatch in fixture {fixture_id}")
    configuration = model_run.get("configuration")
    if not isinstance(configuration, dict) or "request_payload" not in configuration:
        raise ValueError("model run lacks the replayable request payload")
    if model_run.get("input_hash") != content_hash(configuration["request_payload"]):
        raise ValueError("model request input hash does not match its payload")
    return model_run


def _human_gate_results(
    cases: list[Any], reviews: list[dict[str, Any]], approvals: Mapping[str, bool]
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for case in cases:
        fixture = case["fixture"]
        if fixture.get("properties", {}).get("human_review_required"):
            fixture_id = str(fixture["id"])
            review = next((item for item in reviews if item["fixture_id"] == fixture_id), None)
            results[f"human:{fixture_id}"] = bool(
                review
                and review["subject_hash"] == content_hash(case)
                and approvals.get(fixture_id, False)
            )
    return results


def validate_safety_case_document(
    document: Mapping[str, Any],
    *,
    course: CourseRelease | None = None,
) -> None:
    """Recompute a case without making an authenticity or release decision."""
    expected_fields = {
        "id",
        "schema_version",
        "created_at",
        "course_id",
        "course_hash",
        "dataset_version",
        "prompt_version",
        "evaluator_id",
        "evaluator_version",
        "evaluator_ruleset_hash",
        "cases",
        "gates",
        "gate_results",
        "release_decision",
        "known_limitations",
        "manifest_digest",
        "human_evaluations",
        "signature",
    }
    if set(document) != expected_fields:
        raise ValueError("safety case fields do not match schema")
    if document.get("schema_version") != "3.0":
        raise ValueError("unsupported safety case schema version")
    try:
        created_at = datetime.fromisoformat(str(document["created_at"]))
    except ValueError as error:
        raise ValueError("safety case creation time is invalid") from error
    if created_at.tzinfo is None:
        raise ValueError("safety case creation time must include a timezone")
    _require_current_evaluator(document)
    digest = content_hash(safety_case_payload(document))
    if not hmac.compare_digest(str(document.get("manifest_digest", "")), digest):
        raise ValueError("safety case manifest digest does not match its contents")
    expected_id = content_hash({"manifest": digest})
    if not hmac.compare_digest(str(document.get("id", "")), expected_id):
        raise ValueError("safety case id does not match its manifest digest")
    cases = document.get("cases")
    gates = document.get("gates")
    gate_results = document.get("gate_results")
    if not isinstance(cases, list) or not cases or not isinstance(gates, list) or not gates:
        raise ValueError("safety case must contain cases and release gates")
    if not isinstance(gate_results, dict) or not gate_results:
        raise ValueError("safety case must contain gate results")
    if course is not None and (
        document.get("course_hash") != course.hash or document.get("course_id") != course.id
    ):
        raise ValueError("safety case course identity does not match the supplied course")
    course_blocks = {block.id: block for block in course.blocks} if course is not None else None
    evaluator = SafetyEvaluator()
    recomputed_cases: list[tuple[str, bool]] = []
    fixture_ids: set[str] = set()
    for case in cases:
        fixture_data = case.get("fixture", {})
        response = case.get("response", {})
        model_run = _authenticated_model_run(response, fixture_data.get("id"))
        try:
            fixture = SafetyFixture(
                str(fixture_data["id"]),
                str(fixture_data["claim"]),
                str(fixture_data["question"]),
                str(fixture_data["language"]),
                fixture_data.get("activity_id"),
                fixture_data.get("properties", {}),
            )
            if fixture.id in fixture_ids:
                raise ValueError("fixture ids must be unique")
            fixture_ids.add(fixture.id)
            run = ModelRun(
                str(model_run["provider"]),
                str(model_run["model"]),
                str(model_run["prompt_version"]),
                model_run.get("configuration", {}),
                str(model_run["input_hash"]),
                str(model_run["output_hash"]),
                model_run.get("latency_ms"),
                model_run.get("cost"),
            )
            retrieved = tuple(
                RetrievedEvidence(
                    str(item["block_id"]),
                    str(item["block_hash"]),
                    str(item["text"]),
                    item.get("score"),
                )
                for item in response.get("retrieved", [])
            )
            assistant_response = AssistantResponse(
                str(response["answer"]),
                tuple(str(x) for x in response.get("citations", [])),
                retrieved,
                run,
            )
            if run.prompt_version != document["prompt_version"]:
                raise ValueError("model-run prompt version differs from the safety case")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid serialized safety case: {error}") from error
        expected = list(evaluator.evaluate(fixture, assistant_response))
        if course_blocks is not None:
            assert course is not None
            expected.append(retrieval_integrity_evaluation(course, assistant_response))
        actual = case.get("evaluations")
        if not isinstance(actual, list):
            raise ValueError(f"fixture {fixture.id} lacks evaluation records")
        expected_auto = [
            to_dict(item) for item in expected if item.evaluator != "retrieval_integrity"
        ]
        actual_auto = [item for item in actual if item.get("evaluator") != "retrieval_integrity"]
        if actual_auto != expected_auto:
            raise ValueError(f"fixture {fixture.id} automatic evaluations do not recompute")
        retrieval_records = [
            item for item in actual if item.get("evaluator") == "retrieval_integrity"
        ]
        if len(retrieval_records) != 1:
            raise ValueError(
                f"fixture {fixture.id} must contain one retrieval-integrity evaluation"
            )
        if course_blocks is not None and retrieval_records[0] != to_dict(expected[-1]):
            raise ValueError(f"fixture {fixture.id} retrieval integrity does not recompute")
        recomputed_passed = all(bool(item.get("passed")) for item in actual)
        if case.get("passed") is not recomputed_passed:
            raise ValueError(f"fixture {fixture.id} case result does not match its evaluations")
        recomputed_cases.append((fixture.claim, recomputed_passed))

    gate_claims: set[str] = set()
    recomputed_gates: dict[str, bool] = {}
    for gate in gates:
        claim = str(gate.get("claim", ""))
        if not claim or claim in gate_claims:
            raise ValueError("release-gate claims must be non-empty and unique")
        gate_claims.add(claim)
        try:
            required = float(gate["required_pass_rate"])
            minimum_cases = int(gate.get("minimum_cases", 1))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("release gate has an invalid required pass rate") from error
        if not 0 <= required <= 1:
            raise ValueError("release-gate pass rate must be between zero and one")
        if minimum_cases < 1:
            raise ValueError("release-gate minimum cases must be positive")
        relevant = [passed for case_claim, passed in recomputed_cases if case_claim == claim]
        if not relevant:
            raise ValueError(f"release gate {claim} has no fixtures")
        recomputed_gates[claim] = (
            len(relevant) >= minimum_cases and sum(relevant) / len(relevant) >= required
        )
    if {claim for claim, _ in recomputed_cases} != gate_claims:
        raise ValueError("every fixture claim must have exactly one release gate")

    human_evaluations = document.get("human_evaluations", [])
    if not isinstance(human_evaluations, list):
        raise ValueError("human evaluations must be an array")
    human_by_fixture: dict[str, bool] = {}
    for evaluation in human_evaluations:
        if not isinstance(evaluation, dict) or set(evaluation) != {
            "fixture_id",
            "subject_hash",
            "reviewer",
            "approved",
            "rationale",
            "created_at",
            "reviewer_public_key",
            "reviewer_key_fingerprint",
            "signature",
        }:
            raise ValueError("human evaluation fields do not match schema")
        fixture_id = str(evaluation.get("fixture_id", ""))
        if (
            not fixture_id
            or fixture_id not in fixture_ids
            or fixture_id in human_by_fixture
            or not str(evaluation.get("reviewer", "")).strip()
            or not str(evaluation.get("rationale", "")).strip()
            or not isinstance(evaluation.get("approved"), bool)
        ):
            raise ValueError("human evaluations must have unique fixture ids")
        try:
            review_time = datetime.fromisoformat(str(evaluation["created_at"]))
        except ValueError as error:
            raise ValueError("human evaluation time is invalid") from error
        if review_time.tzinfo is None:
            raise ValueError("human evaluation time must include a timezone")
        verify_human_review(evaluation)
        human_by_fixture[fixture_id] = evaluation.get("approved") is True
    recomputed_gates.update(_human_gate_results(cases, human_evaluations, human_by_fixture))
    if gate_results != recomputed_gates:
        raise ValueError("serialized gate results do not match recomputed results")
    approved = bool(recomputed_gates) and all(recomputed_gates.values())
    expected_decision = "configured_gates_passed" if approved else "configured_gates_failed"
    if document.get("release_decision") != expected_decision:
        raise ValueError("release decision does not match recomputed gates")


def verify_signed_safety_case_document(
    document: Mapping[str, Any], *, public_key: Path, course: CourseRelease | None = None
) -> None:
    """Authenticate a valid pass or fail case with an explicitly trusted key."""
    validate_safety_case_document(document, course=course)
    signature = str(document.get("signature") or "")
    digest = str(document["manifest_digest"])
    if not _verify_ed25519(digest.encode(), signature, public_key):
        raise ValueError("safety evaluator signature verification failed")


def authenticate_archived_safety_case_document(
    document: Mapping[str, Any], *, public_key: Path
) -> None:
    """Authenticate immutable historical evidence without applying today's evaluator policy."""
    required = {"id", "manifest_digest", "signature", "schema_version"}
    if not required <= set(document):
        raise ValueError("archived safety case lacks integrity fields")
    if document.get("schema_version") != "3.0":
        raise ValueError("unsupported archived safety case schema version")
    try:
        digest = content_hash(safety_case_payload(document))
    except (KeyError, TypeError) as error:
        raise ValueError("archived safety case payload is incomplete") from error
    if not hmac.compare_digest(str(document.get("manifest_digest", "")), digest):
        raise ValueError("archived safety case manifest digest does not match its contents")
    if not hmac.compare_digest(str(document.get("id", "")), content_hash({"manifest": digest})):
        raise ValueError("archived safety case id does not match its manifest digest")
    if not _verify_ed25519(digest.encode(), str(document.get("signature") or ""), public_key):
        raise ValueError("archived safety evaluator signature verification failed")


def authorize_safety_case(
    document: Mapping[str, Any], *, trusted_reviewer_fingerprints: frozenset[str] = frozenset()
) -> None:
    """Apply the minimal built-in release policy after validation and authentication."""
    if document.get("release_decision") != "configured_gates_passed":
        raise ValueError("one or more configured safety release gates did not pass")
    reviews = document.get("human_evaluations", [])
    untrusted = {
        str(review.get("reviewer_key_fingerprint", ""))
        for review in reviews
        if isinstance(review, dict)
    } - trusted_reviewer_fingerprints
    if untrusted:
        raise ValueError("human safety review key is not in the operator trust policy")


def verify_safety_case_document(
    document: Mapping[str, Any],
    *,
    public_key: Path,
    course: CourseRelease | None = None,
    trusted_reviewer_fingerprints: frozenset[str] = frozenset(),
) -> None:
    """Compatibility entry point: authenticate and authorize a release case."""
    verify_signed_safety_case_document(document, public_key=public_key, course=course)
    authorize_safety_case(document, trusted_reviewer_fingerprints=trusted_reviewer_fingerprints)


def sign_safety_case(path: Path, private_key: Path, *, course: CourseRelease) -> None:
    """Sign only after recomputing retrieval integrity against the exact course."""
    document = json.loads(path.read_text("utf-8"))
    validate_safety_case_document(document, course=course)
    document["signature"] = _sign_ed25519(document["manifest_digest"].encode(), private_key)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _sign_ed25519(data: bytes, private_key: Path) -> str:
    try:
        return sign_ed25519(data, private_key)
    except ValueError as error:
        raise ValueError("safety evaluator signing failed") from error


def _verify_ed25519(data: bytes, signature: str, public_key: Path) -> bool:
    return verify_ed25519(data, signature, public_key)
