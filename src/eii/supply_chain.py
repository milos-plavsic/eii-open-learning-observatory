"""Deterministic release checksums and dependency-free SPDX evidence."""

from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib.metadata import metadata
from pathlib import Path

from .release_signing import sign_release_evidence as sign_release_evidence
from .release_signing import verify_approval_evidence as verify_approval_evidence
from .release_signing import verify_signed_release as verify_signed_release

RUNTIME_LICENSES = {"defusedxml": "PSF-2.0", "rfc8785": "Apache-2.0"}


def runtime_components(
    pyproject: Path = Path("pyproject.toml"),
) -> tuple[tuple[str, str, str, str], ...]:
    """Derive the SBOM inventory from exact runtime declarations, failing on drift."""
    if pyproject.is_file():
        requirements = tomllib.loads(pyproject.read_text("utf-8"))["project"].get(
            "dependencies", []
        )
    else:
        requirements = [
            requirement.split(";", 1)[0].strip()
            for requirement in metadata("eii-observatory").get_all("Requires-Dist", [])
            if "extra ==" not in requirement
        ]
    components = []
    for requirement in requirements:
        if "==" not in requirement or requirement.count("==") != 1:
            raise ValueError(f"runtime dependency must be exactly pinned for SBOM: {requirement}")
        name, version = (part.strip() for part in requirement.split("=="))
        normalized = name.casefold().replace("_", "-")
        license_id = RUNTIME_LICENSES.get(normalized)
        if not name or not version or license_id is None:
            raise ValueError(f"runtime dependency lacks approved SPDX metadata: {requirement}")
        components.append((normalized, version, license_id, f"pkg:pypi/{normalized}@{version}"))
    return tuple(sorted(components))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_kind(path: Path) -> str:
    if path.suffix == ".whl" and zipfile.is_zipfile(path):
        return "python-wheel"
    if path.name.endswith(".tar.gz") and tarfile.is_tarfile(path):
        return "python-sdist"
    raise ValueError(f"unsupported or invalid release artifact: {path}")


def normalize_sdist_gzip(path: Path) -> None:
    """Canonicalize tar ownership/time/order and the gzip header."""
    if not path.name.endswith(".tar.gz") or not tarfile.is_tarfile(path):
        raise ValueError(f"not a valid gzip source distribution: {path}")
    source_bytes = gzip.decompress(path.read_bytes())
    destination = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(source_bytes), mode="r:") as source,
        tarfile.open(fileobj=destination, mode="w", format=tarfile.PAX_FORMAT) as target,
    ):
        for original in sorted(source.getmembers(), key=lambda member: member.name):
            member = copy.copy(original)
            member.mtime = member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.pax_headers = {}
            stream = source.extractfile(original) if original.isfile() else None
            target.addfile(member, stream)
    path.write_bytes(gzip.compress(destination.getvalue(), compresslevel=9, mtime=0))


def build_release_evidence(
    artifacts: Iterable[Path],
    *,
    project: str,
    version: str,
    revision: str,
    source_digest: str,
    created_at: str | None = None,
) -> dict[str, object]:
    if not source_digest.startswith("sha256:") or len(source_digest) != 71:
        raise ValueError("source digest must be a sha256-prefixed source archive digest")
    paths = tuple(sorted((path.resolve() for path in artifacts), key=lambda item: item.name))
    if not paths:
        raise ValueError("at least one release artifact is required")
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("release artifact names must be unique")
    files = [
        {
            "name": path.name,
            "kind": artifact_kind(path),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]
    supplied_time = (
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created_at
        else datetime.now(UTC)
    )
    if supplied_time.tzinfo is None:
        raise ValueError("release evidence creation time must include a timezone")
    timestamp = supplied_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    components = runtime_components()
    namespace_seed = json.dumps([project, version, revision, files], sort_keys=True).encode()
    namespace = "https://eii.edu.eu/spdx/" + hashlib.sha256(namespace_seed).hexdigest()
    return {
        "schema_version": "1.0",
        "project": project,
        "version": version,
        "revision": revision,
        "source_digest": source_digest,
        "created_at": timestamp,
        "artifacts": files,
        "spdx": {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"{project}-{version}",
            "documentNamespace": namespace,
            "creationInfo": {"created": timestamp, "creators": ["Tool: eii-observatory"]},
            "packages": [
                {
                    "name": project,
                    "SPDXID": "SPDXRef-Package",
                    "versionInfo": version,
                    "downloadLocation": "NOASSERTION",
                    "supplier": "Organization: Education Improvement Institute",
                    "filesAnalyzed": False,
                    "licenseConcluded": "MIT",
                    "licenseDeclared": "MIT",
                    "primaryPackagePurpose": "APPLICATION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": f"pkg:pypi/{project}@{version}",
                        }
                    ],
                },
                *[
                    {
                        "name": name,
                        "SPDXID": f"SPDXRef-Dependency-{name}",
                        "versionInfo": dependency_version,
                        "downloadLocation": "NOASSERTION",
                        "supplier": "NOASSERTION",
                        "filesAnalyzed": False,
                        "licenseConcluded": license_id,
                        "licenseDeclared": license_id,
                        "externalRefs": [
                            {
                                "referenceCategory": "PACKAGE-MANAGER",
                                "referenceType": "purl",
                                "referenceLocator": purl,
                            }
                        ],
                    }
                    for name, dependency_version, license_id, purl in components
                ],
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package",
                },
                *[
                    {
                        "spdxElementId": "SPDXRef-Package",
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": f"SPDXRef-Dependency-{name}",
                    }
                    for name, *_ in components
                ],
            ],
        },
    }


def verify_spdx_document(document: object) -> None:
    """Validate the release SBOM's identities and dependency graph."""
    if not isinstance(document, dict) or document.get("spdxVersion") != "SPDX-2.3":
        raise ValueError("SBOM is not an SPDX 2.3 document")
    packages = document.get("packages")
    relationships = document.get("relationships")
    if not isinstance(packages, list) or not isinstance(relationships, list):
        raise ValueError("SBOM packages and relationships must be arrays")
    package_ids = [item.get("SPDXID") for item in packages if isinstance(item, dict)]
    if len(package_ids) != len(packages) or len(package_ids) != len(set(package_ids)):
        raise ValueError("SBOM package identities must be complete and unique")
    known = {"SPDXRef-DOCUMENT", *package_ids}
    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or relationship.get("spdxElementId") not in known
            or relationship.get("relatedSpdxElement") not in known
            or relationship.get("relationshipType") not in {"DESCRIBES", "DEPENDS_ON"}
        ):
            raise ValueError("SBOM contains an invalid relationship")
    expected_dependencies = {f"SPDXRef-Dependency-{name}" for name, *_ in runtime_components()}
    actual_dependencies = {
        relationship["relatedSpdxElement"]
        for relationship in relationships
        if relationship["relationshipType"] == "DEPENDS_ON"
    }
    if actual_dependencies != expected_dependencies:
        raise ValueError("SBOM dependency graph differs from declared runtime dependencies")


def write_release_evidence(evidence: dict[str, object], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "release-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    artifacts = evidence["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("release evidence artifacts must be a list")
    lines = [f"{item['sha256']}  {item['name']}" for item in artifacts]
    (destination / "SHA256SUMS").write_text("\n".join(lines) + "\n", "ascii")
    verify_spdx_document(evidence["spdx"])
    (destination / "sbom.spdx.json").write_text(
        json.dumps(evidence["spdx"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )


def verify_release_evidence(evidence_path: Path, artifact_directory: Path) -> None:
    evidence = json.loads(evidence_path.read_text("utf-8"))
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("release evidence contains no artifacts")
    verify_spdx_document(evidence.get("spdx"))
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"name", "kind", "size", "sha256"}:
            raise ValueError("release artifact record is invalid")
        name = item.get("name")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("release artifact name must be a basename")
        path = artifact_directory / name
        if not path.is_file() or artifact_kind(path) != item["kind"]:
            raise ValueError(f"release artifact missing or invalid: {path.name}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"release artifact checksum mismatch: {path.name}")
