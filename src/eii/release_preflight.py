"""Fail-closed checks binding release artifacts to the producer version."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Mapping
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from ._version import __version__


def validate_attestation_receipt(
    document: object, *, predicate_type: str, artifact_hashes: set[str]
) -> None:
    """Validate structured output produced by ``gh attestation verify --format=json``."""
    if not isinstance(document, list) or not document:
        raise ValueError("attestation receipt must contain verified results")
    observed: set[str] = set()
    for result in document:
        if not isinstance(result, dict) or not isinstance(result.get("verificationResult"), dict):
            raise ValueError("attestation receipt result is invalid")
        verification = result["verificationResult"]
        statement = verification.get("statement")
        timestamps = verification.get("verifiedTimestamps")
        signature = verification.get("signature")
        if (
            not isinstance(statement, dict)
            or statement.get("predicateType") != predicate_type
            or not isinstance(statement.get("subject"), list)
            or not isinstance(timestamps, list)
            or not timestamps
            or not isinstance(signature, dict)
            or not isinstance(signature.get("certificate"), dict)
        ):
            raise ValueError("attestation receipt verification result is incomplete")
        for subject in statement["subject"]:
            if isinstance(subject, dict) and isinstance(subject.get("digest"), dict):
                digest = subject["digest"].get("sha256")
                if isinstance(digest, str):
                    observed.add(digest)
    if not artifact_hashes <= observed:
        raise ValueError("attestation receipt does not cover every release artifact")


def write_approval_evidence(
    destination: Path,
    artifacts: tuple[Path, ...],
    *,
    version: str,
    revision: str,
    candidate_run_id: str,
    approval_run_id: str,
    repository: str,
    actor: str,
    environment: str,
    run_url: str,
    receipts: Mapping[str, Path],
) -> None:
    """Write machine-verifiable evidence for a successful promotion preflight."""
    bounded = {
        "revision": revision,
        "candidate_run_id": candidate_run_id,
        "approval_run_id": approval_run_id,
        "repository": repository,
        "actor": actor,
        "environment": environment,
        "run_url": run_url,
    }
    if any(
        not value or len(value) > 512 or any(ord(char) < 32 for char in value)
        for value in bounded.values()
    ):
        raise ValueError("approval evidence metadata must be bounded non-empty text")
    files = {
        artifact.name: {
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size": artifact.stat().st_size,
        }
        for artifact in sorted(artifacts, key=lambda path: path.name)
    }
    if len(files) != len(artifacts):
        raise ValueError("approval artifact names must be unique")
    expected_checks = {
        "candidate-workflow-success",
        "main-branch-revision-bound",
        "artifact-version-binding",
        "artifact-build-provenance",
        "artifact-sbom-attestation",
    }
    if set(receipts) != expected_checks or any(not path.is_file() for path in receipts.values()):
        raise ValueError("approval evidence requires one file receipt for every verified check")
    receipt_directory = destination.parent / "approval-receipts"
    receipt_directory.mkdir(parents=True, exist_ok=True)
    receipt_records = {}
    artifact_hashes: set[str] = {str(record["sha256"]) for record in files.values()}
    for name, source in sorted(receipts.items()):
        target = receipt_directory / f"{name}.json"
        shutil.copyfile(source, target)
        payload = target.read_bytes()
        if not payload:
            raise ValueError(f"approval receipt is empty: {name}")
        try:
            receipt_document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"approval receipt is not valid JSON: {name}") from error
        if name == "candidate-workflow-success" and (
            not isinstance(receipt_document, dict)
            or str(receipt_document.get("id")) != candidate_run_id
            or receipt_document.get("conclusion") != "success"
            or receipt_document.get("name") != "Release candidate"
            or receipt_document.get("head_branch") != "main"
            or receipt_document.get("head_sha") != revision
        ):
            raise ValueError("candidate workflow receipt does not prove the requested run")
        if name != "candidate-workflow-success" and (
            name in {"main-branch-revision-bound", "artifact-version-binding"}
            and (
                not isinstance(receipt_document, dict)
                or receipt_document.get("revision") != revision
                or receipt_document.get("version") != version
                or not isinstance(receipt_document.get("source_digest"), str)
                or len(receipt_document["source_digest"]) != 71
                or not receipt_document["source_digest"].startswith("sha256:")
            )
        ):
            raise ValueError(f"source binding receipt is invalid: {name}")
        if name in {"artifact-build-provenance", "artifact-sbom-attestation"}:
            validate_attestation_receipt(
                receipt_document,
                predicate_type=(
                    "https://slsa.dev/provenance/v1"
                    if name == "artifact-build-provenance"
                    else "https://spdx.dev/Document/v2.3"
                ),
                artifact_hashes=artifact_hashes,
            )
        receipt_records[name] = {
            "path": target.relative_to(destination.parent).as_posix(),
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "media_type": "application/json",
        }
    document = {
        "schema_version": "1.0",
        "project": "eii-observatory",
        "version": version,
        **bounded,
        "checks": sorted(expected_checks),
        "artifacts": files,
        "receipts": receipt_records,
    }
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", "utf-8")


def require_clean_source_tree(repository: Path = Path("."), *, revision: str | None = None) -> str:
    """Return the exact Git revision only when the tracked and untracked tree is clean."""
    root = repository.resolve()
    try:
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("release source must be an accessible Git worktree") from error
    if status:
        raise ValueError("release source tree is dirty; commit every tracked and untracked input")
    if revision is not None and revision != actual:
        raise ValueError(f"release revision {revision!r} does not match source HEAD {actual!r}")
    return actual


def artifact_metadata(path: Path) -> Message:
    """Read core metadata from a wheel or source distribution."""
    if path.suffix == ".whl" and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"wheel must contain exactly one METADATA file: {path.name}")
            metadata = archive.read(names[0])
    elif path.name.endswith(".tar.gz") and tarfile.is_tarfile(path):
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
            ]
            if len(members) != 1:
                raise ValueError(f"sdist must contain exactly one PKG-INFO file: {path.name}")
            stream = archive.extractfile(members[0])
            if stream is None:
                raise ValueError(f"sdist PKG-INFO is unreadable: {path.name}")
            metadata = stream.read()
    else:
        raise ValueError(f"unsupported release artifact: {path.name}")
    return BytesParser().parsebytes(metadata)


def artifact_version(path: Path) -> str:
    """Read the package version from a wheel or source distribution."""
    version = artifact_metadata(path).get("Version")
    if not version:
        raise ValueError(f"artifact metadata has no Version: {path.name}")
    return version


def validate_release_candidate(
    artifacts: tuple[Path, ...], *, expected_version: str, tag: str | None = None
) -> None:
    """Require package, producer, tag, wheel, and sdist versions to agree."""
    if expected_version != __version__:
        raise ValueError(
            f"expected version {expected_version!r} does not match producer {__version__!r}"
        )
    if tag is not None and tag != f"v{__version__}":
        raise ValueError(f"tag {tag!r} does not match producer version v{__version__}")
    kinds = {"wheel": 0, "sdist": 0}
    if len(artifacts) != 2:
        raise ValueError("release candidate requires exactly one wheel and one sdist")
    for artifact in artifacts:
        metadata = artifact_metadata(artifact)
        version = metadata.get("Version")
        name = metadata.get("Name")
        if not version:
            raise ValueError(f"artifact metadata has no Version: {artifact.name}")
        if version != __version__:
            raise ValueError(
                f"artifact {artifact.name} version {version!r} does not match {__version__!r}"
            )
        if not name or name.casefold().replace("_", "-") != "eii-observatory":
            raise ValueError(
                f"artifact project name does not match eii-observatory: {artifact.name}"
            )
        kind = "wheel" if artifact.suffix == ".whl" else "sdist"
        expected_prefix = f"eii_observatory-{__version__}-"
        if kind == "wheel" and not artifact.name.startswith(expected_prefix):
            raise ValueError(f"wheel filename does not match producer version: {artifact.name}")
        if kind == "sdist" and artifact.name != f"eii_observatory-{__version__}.tar.gz":
            raise ValueError(f"sdist filename does not match producer version: {artifact.name}")
        kinds[kind] += 1
    if kinds != {"wheel": 1, "sdist": 1}:
        raise ValueError("release candidate requires exactly one wheel and one sdist")
