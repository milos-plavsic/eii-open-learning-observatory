"""Signed release manifests and machine-bound approval verification."""

from __future__ import annotations

import json
from pathlib import Path

from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519
from .domain import canonical_json
from .release_preflight import validate_attestation_receipt


def _sha256_file(path: Path) -> str:
    from .supply_chain import sha256_file

    return sha256_file(path)


def sign_release_evidence(evidence_directory: Path, private_key: Path, public_key: Path) -> Path:
    required = ("SHA256SUMS", "release-evidence.json", "sbom.spdx.json")
    missing = [name for name in required if not (evidence_directory / name).is_file()]
    if missing:
        raise ValueError(f"release evidence file is missing: {', '.join(missing)}")
    evidence = json.loads((evidence_directory / "release-evidence.json").read_text("utf-8"))
    included: tuple[str, ...] = required
    if (evidence_directory / "APPROVAL.json").is_file():
        receipt_files = verify_approval_evidence(evidence_directory / "APPROVAL.json", evidence)
        included = (*required, "APPROVAL.json", *sorted(receipt_files))
    manifest = {
        "schema_version": "2.0",
        "project": evidence.get("project"),
        "version": evidence.get("version"),
        "revision": evidence.get("revision"),
        "files": {
            name: {
                "sha256": _sha256_file(evidence_directory / name),
                "size": (evidence_directory / name).stat().st_size,
            }
            for name in included
        },
    }
    manifest_path = evidence_directory / "RELEASE-MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    signed_payload = canonical_json(manifest).encode("utf-8")
    signature = sign_ed25519(signed_payload, private_key)
    if not verify_ed25519(signed_payload, signature, public_key):
        raise ValueError("release private and public keys do not match")
    document = {
        "algorithm": "Ed25519",
        "key_fingerprint": public_key_fingerprint(public_key),
        "signature": signature,
    }
    destination = evidence_directory / "RELEASE-MANIFEST.ed25519.json"
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", "utf-8")
    return destination


def verify_signed_release(
    evidence_directory: Path, artifact_directory: Path, public_key: Path
) -> None:
    from .supply_chain import verify_release_evidence

    manifest_path = evidence_directory / "RELEASE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    document = json.loads((evidence_directory / "RELEASE-MANIFEST.ed25519.json").read_text("utf-8"))
    if (
        set(document) != {"algorithm", "key_fingerprint", "signature"}
        or document["algorithm"] != "Ed25519"
    ):
        raise ValueError("release signature document is invalid")
    if document["key_fingerprint"] != public_key_fingerprint(public_key):
        raise ValueError("release signature key fingerprint does not match")
    if not verify_ed25519(
        canonical_json(manifest).encode("utf-8"), str(document["signature"]), public_key
    ):
        raise ValueError("release manifest signature verification failed")
    if (
        set(manifest) != {"schema_version", "project", "version", "revision", "files"}
        or manifest["schema_version"] != "2.0"
        or not isinstance(manifest["files"], dict)
    ):
        raise ValueError("release manifest is invalid")
    core = {"SHA256SUMS", "release-evidence.json", "sbom.spdx.json"}
    actual_files = set(manifest["files"])
    if not (actual_files == core or "APPROVAL.json" in actual_files):
        raise ValueError("release manifest file set is invalid")
    for name in sorted(actual_files):
        path = evidence_directory / name
        record = manifest["files"][name]
        if (
            not path.is_file()
            or set(record) != {"sha256", "size"}
            or record["sha256"] != _sha256_file(path)
            or record["size"] != path.stat().st_size
        ):
            raise ValueError(f"signed release evidence mismatch: {name}")
    evidence = json.loads((evidence_directory / "release-evidence.json").read_text("utf-8"))
    if any(manifest[key] != evidence.get(key) for key in ("project", "version", "revision")):
        raise ValueError("release manifest identity does not match release evidence")
    if json.loads((evidence_directory / "sbom.spdx.json").read_text("utf-8")) != evidence.get(
        "spdx"
    ):
        raise ValueError("signed SBOM does not match release evidence")
    if "APPROVAL.json" in actual_files:
        receipts = verify_approval_evidence(evidence_directory / "APPROVAL.json", evidence)
        if actual_files != core | {"APPROVAL.json"} | receipts:
            raise ValueError("release manifest receipt file set is invalid")
    verify_release_evidence(evidence_directory / "release-evidence.json", artifact_directory)


def verify_approval_evidence(path: Path, release_evidence: dict[str, object]) -> set[str]:
    """Validate a promotion preflight record before binding it into a signature."""
    document = json.loads(path.read_text("utf-8"))
    required = {
        "schema_version",
        "project",
        "version",
        "revision",
        "candidate_run_id",
        "approval_run_id",
        "repository",
        "actor",
        "environment",
        "run_url",
        "checks",
        "artifacts",
        "receipts",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ValueError("release approval evidence is invalid")
    if document["schema_version"] != "1.0" or any(
        document[key] != release_evidence.get(key) for key in ("project", "version", "revision")
    ):
        raise ValueError("release approval identity does not match release evidence")
    text_fields = tuple(required - {"checks", "artifacts", "receipts"})
    if any(
        not isinstance(document[key], str)
        or not document[key]
        or len(document[key]) > 512
        or any(ord(char) < 32 for char in document[key])
        for key in text_fields
    ) or not document["run_url"].startswith("https://"):
        raise ValueError("release approval metadata is invalid")
    expected_checks = {
        "candidate-workflow-success",
        "main-branch-revision-bound",
        "artifact-version-binding",
        "artifact-build-provenance",
        "artifact-sbom-attestation",
    }
    if not isinstance(document["checks"], list) or set(document["checks"]) != expected_checks:
        raise ValueError("release approval checks are incomplete")
    receipts = document["receipts"]
    if not isinstance(receipts, dict) or set(receipts) != expected_checks:
        raise ValueError("release approval receipts are invalid")
    receipt_files: set[str] = set()
    for name, record in receipts.items():
        suffix = "json"
        expected_path = f"approval-receipts/{name}.{suffix}"
        expected_media = "application/json"
        receipt = path.parent / expected_path
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size", "media_type"}
            or record["path"] != expected_path
            or record["media_type"] != expected_media
            or not receipt.is_file()
            or record["size"] != receipt.stat().st_size
            or record["size"] < 1
            or record["sha256"] != "sha256:" + _sha256_file(receipt)
        ):
            raise ValueError(f"release approval receipt is invalid: {name}")
        receipt_files.add(expected_path)

    candidate = json.loads(
        (path.parent / receipts["candidate-workflow-success"]["path"]).read_text("utf-8")
    )
    if (
        not isinstance(candidate, dict)
        or str(candidate.get("id")) != document["candidate_run_id"]
        or candidate.get("conclusion") != "success"
        or candidate.get("name") != "Release candidate"
        or candidate.get("head_branch") != "main"
        or candidate.get("head_sha") != document["revision"]
    ):
        raise ValueError("candidate workflow receipt content is invalid")
    for check in ("main-branch-revision-bound", "artifact-version-binding"):
        binding = json.loads((path.parent / receipts[check]["path"]).read_text("utf-8"))
        if binding != {
            "revision": document["revision"],
            "source_digest": release_evidence.get("source_digest"),
            "version": document["version"],
        }:
            raise ValueError(f"release binding receipt content is invalid: {check}")
    artifacts = document["artifacts"]
    records = release_evidence.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(records, list):
        raise ValueError("release approval artifacts are invalid")
    expected = {
        item["name"]: {"sha256": item["sha256"], "size": item["size"]}
        for item in records
        if isinstance(item, dict)
    }
    if artifacts != expected:
        raise ValueError("release approval artifacts do not match release evidence")
    artifact_hashes = {record["sha256"] for record in expected.values()}
    for check, predicate_type in (
        ("artifact-build-provenance", "https://slsa.dev/provenance/v1"),
        ("artifact-sbom-attestation", "https://spdx.dev/Document/v2.3"),
    ):
        receipt_document = json.loads((path.parent / receipts[check]["path"]).read_text("utf-8"))
        validate_attestation_receipt(
            receipt_document, predicate_type=predicate_type, artifact_hashes=artifact_hashes
        )
    return receipt_files
