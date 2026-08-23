"""Creation and strict verification of signed offline-appliance archives."""

from __future__ import annotations

import hashlib
import hmac
import json
import stat
import unicodedata
import uuid
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .appliance_types import PackageManifest
from .crypto import sign_ed25519, verify_ed25519

MAX_PACKAGE_FILES = 10_000
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
MANIFEST_FIELDS = {"schema_version", "package_id", "version", "created_at", "files", "metadata"}


def safe_member_name(name: str) -> str:
    pure = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or pure.is_absolute()
        or ".." in pure.parts
        or any(not part or part in {".", ".."} for part in pure.parts)
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError(f"unsafe package path: {name}")
    return unicodedata.normalize("NFC", name).casefold()


def validate_unique_names(names: list[str]) -> None:
    if len(names) > MAX_PACKAGE_FILES + 2:
        raise ValueError("package contains too many members")
    normalized = [safe_member_name(name) for name in names]
    if len(normalized) != len(set(normalized)):
        raise ValueError("package contains duplicate or cross-platform-colliding paths")


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def create_package(
    inputs: tuple[Path, ...],
    destination: Path,
    *,
    version: str,
    private_key: Path,
    metadata: dict[str, object] | None = None,
) -> PackageManifest:
    entries: list[tuple[Path, str]] = []
    for source in inputs:
        if source.is_symlink():
            raise ValueError(f"package inputs must not be symbolic links: {source}")
        source = source.resolve()
        if source.is_dir():
            for item in sorted(source.rglob("*")):
                if item.is_symlink():
                    raise ValueError(f"package inputs must not contain symbolic links: {item}")
                if item.is_file():
                    entries.append(
                        (item, f"content/{source.name}/{item.relative_to(source).as_posix()}")
                    )
        elif source.is_file():
            entries.append((source, f"content/{source.name}"))
        else:
            raise ValueError(f"package input does not exist: {source}")
    if not entries:
        raise ValueError("package requires at least one file")
    validate_unique_names([name for _, name in entries])
    if len(version.encode()) > 200 or not version.strip():
        raise ValueError("package version must be non-empty and at most 200 bytes")
    files = {archive: _digest(source) for source, archive in entries}
    if len(json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False).encode()) > 1_048_576:
        raise ValueError("package metadata exceeds 1 MiB")
    manifest = PackageManifest(
        "2.0", str(uuid.uuid4()), version, datetime.now(UTC).isoformat(), files, metadata or {}
    )
    manifest_bytes = json.dumps(
        asdict(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, name in entries:
            archive.write(source, name)
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("manifest.signature", sign_ed25519(manifest_bytes, private_key))
    return manifest


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def verify_package(package: Path, *, public_key: Path) -> PackageManifest:
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        validate_unique_names(names)
        total_size = 0
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"package must not contain symbolic links: {info.filename}")
            if info.is_dir() or info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"invalid or oversized package member: {info.filename}")
            total_size += info.file_size
            if info.file_size and info.compress_size == 0:
                raise ValueError(f"invalid compressed size: {info.filename}")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise ValueError(f"suspicious compression ratio: {info.filename}")
        if total_size > MAX_PACKAGE_BYTES:
            raise ValueError("package uncompressed size exceeds 2 GiB")
        manifest_bytes = archive.read("manifest.json")
        signature = archive.read("manifest.signature").decode()
        if signature.startswith("hmac-sha256:"):
            raise ValueError("symmetric-key/HMAC appliance packages are unsupported")
        if not verify_ed25519(manifest_bytes, signature, public_key):
            raise ValueError("package signature verification failed")
        data = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != MANIFEST_FIELDS:
            raise ValueError("package manifest fields do not match schema")
        if data.get("schema_version") != "2.0":
            raise ValueError("unsupported package manifest schema version")
        try:
            uuid.UUID(str(data["package_id"]))
            created_at = datetime.fromisoformat(str(data["created_at"]))
        except (ValueError, TypeError) as error:
            raise ValueError("package manifest identity or timestamp is invalid") from error
        if (
            created_at.tzinfo is None
            or not isinstance(data.get("files"), dict)
            or not data["files"]
            or not isinstance(data.get("metadata"), dict)
            or not isinstance(data.get("version"), str)
            or not str(data["version"]).strip()
            or len(str(data["version"]).encode()) > 200
        ):
            raise ValueError("package manifest requires a timezone and files")
        if set(names) != set(data["files"]) | {"manifest.json", "manifest.signature"}:
            raise ValueError("archive members do not exactly match the signed manifest")
        for name, expected_hash in data["files"].items():
            if (
                not isinstance(expected_hash, str)
                or len(expected_hash) != 71
                or not expected_hash.startswith("sha256:")
                or any(char not in "0123456789abcdef" for char in expected_hash[7:])
            ):
                raise ValueError(f"invalid content hash declaration: {name}")
            actual = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
            if not hmac.compare_digest(actual, expected_hash):
                raise ValueError(f"content hash mismatch: {name}")
    return PackageManifest(**data)
