"""Fail-closed checks binding release artifacts to the producer version."""

from __future__ import annotations

import subprocess
import tarfile
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from ._version import __version__


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
