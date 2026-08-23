"""Snapshot-safe authentication and authorization for Observatory audit directories."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519
from .domain import canonical_json
from .evidence import load_audit_directory

AUDIT_FILES = ("evidence.json", "alignments.json", "translation-status.json", "index.html")
MANIFEST_NAME = "AUDIT-MANIFEST.json"
SIGNATURE_NAME = "AUDIT-MANIFEST.ed25519.json"
DEFAULT_PURPOSE = "course-quality-audit"
MAX_AUDIT_FILE_BYTES = 128 * 1024 * 1024
MAX_AUDIT_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FUTURE_SKEW_SECONDS = 300


@contextmanager
def _signing_lock(directory: Path) -> Iterator[None]:
    """Serialize signers without making the lock file part of the evidence package."""
    path = directory / ".eii-audit-sign.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):  # pragma: no branch - absent on Windows
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("audit signing lock must be a regular file")
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows exercises this in native CI
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        yield
    finally:
        os.close(descriptor)


def _snapshot(directory: Path) -> dict[str, bytes]:
    files = {}
    total = 0
    for name in AUDIT_FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"audit input must be a regular non-symbolic file: {name}")
        size = path.stat().st_size
        if size > MAX_AUDIT_FILE_BYTES or total + size > MAX_AUDIT_TOTAL_BYTES:
            raise ValueError("audit input exceeds the bounded package size")
        value = path.read_bytes()
        if len(value) != size:
            raise ValueError(f"audit input changed while it was read: {name}")
        files[name] = value
        total += size
    return files


def _validate_snapshot(files: dict[str, bytes]) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, value in files.items():
            (root / name).write_bytes(value)
        return load_audit_directory(root).id


def _atomic_json(path: Path, value: object) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sign_audit_directory(
    directory: Path,
    private_key: Path,
    public_key: Path,
    *,
    signer_id: str,
    purpose: str = DEFAULT_PURPOSE,
    created_at: str | None = None,
) -> Path:
    if not signer_id.strip() or not purpose.strip():
        raise ValueError("audit signer identity and purpose must be non-empty")
    timestamp = created_at or datetime.now(UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise ValueError("audit signing time is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("audit signing time must include a timezone")
    with _signing_lock(directory):
        files = _snapshot(directory)
        bundle_id = _validate_snapshot(files)
        fingerprint = public_key_fingerprint(public_key)
        manifest = {
            "schema_version": "2.0",
            "bundle_id": bundle_id,
            "created_at": timestamp,
            "signer_id": signer_id,
            "signer_key_fingerprint": fingerprint,
            "purpose": purpose,
            "files": {
                name: {
                    "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
                    "size": len(value),
                }
                for name, value in files.items()
            },
        }
        payload = canonical_json(manifest).encode("utf-8")
        signature = sign_ed25519(payload, private_key)
        if not verify_ed25519(payload, signature, public_key):
            raise ValueError("audit signing private and public keys do not match")
        if _snapshot(directory) != files:
            raise ValueError("audit directory changed while it was being signed")
        _atomic_json(directory / MANIFEST_NAME, manifest)
        signature_path = directory / SIGNATURE_NAME
        _atomic_json(signature_path, {"algorithm": "Ed25519", "signature": signature})
    return signature_path


def verify_signed_audit(
    directory: Path,
    public_key: Path,
    *,
    authorization_policy: Path | None = None,
    expected_purpose: str | None = None,
    at_time: datetime | None = None,
) -> str:
    files = _snapshot(directory)
    manifest = json.loads((directory / MANIFEST_NAME).read_text("utf-8"))
    signature = json.loads((directory / SIGNATURE_NAME).read_text("utf-8"))
    required = {
        "schema_version",
        "bundle_id",
        "created_at",
        "signer_id",
        "signer_key_fingerprint",
        "purpose",
        "files",
    }
    fingerprint = public_key_fingerprint(public_key)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest["schema_version"] != "2.0"
        or not isinstance(manifest["bundle_id"], str)
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != set(AUDIT_FILES)
    ):
        raise ValueError("signed audit manifest is invalid")
    if (
        not isinstance(manifest["signer_id"], str)
        or not isinstance(manifest["purpose"], str)
        or not isinstance(manifest["signer_key_fingerprint"], str)
        or not isinstance(manifest["created_at"], str)
        or not manifest["signer_id"].strip()
        or not manifest["purpose"].strip()
    ):
        raise ValueError("signed audit identity, purpose, and time are invalid")
    if expected_purpose is not None and manifest["purpose"] != expected_purpose:
        raise ValueError("signed audit purpose does not match the required purpose")
    try:
        signed_at = datetime.fromisoformat(manifest["created_at"])
    except ValueError as error:
        raise ValueError("signed audit time is invalid") from error
    if signed_at.tzinfo is None:
        raise ValueError("signed audit identity, purpose, and time are invalid")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "signature"}
        or signature["algorithm"] != "Ed25519"
        or manifest["signer_key_fingerprint"] != fingerprint
        or not verify_ed25519(
            canonical_json(manifest).encode("utf-8"), str(signature["signature"]), public_key
        )
    ):
        raise ValueError("signed audit authentication failed")
    for name, value in files.items():
        record = manifest["files"][name]
        expected = {
            "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
            "size": len(value),
        }
        if not isinstance(record, dict) or set(record) != {"sha256", "size"} or record != expected:
            raise ValueError(f"signed audit file mismatch: {name}")
    bundle_id = _validate_snapshot(files)
    if manifest["bundle_id"] != bundle_id:
        raise ValueError("signed audit bundle identity does not match its content")
    verification_time = at_time or datetime.now(UTC)
    if verification_time.tzinfo is None:
        raise ValueError("audit authorization verification time must include a timezone")
    if signed_at.timestamp() > verification_time.timestamp() + MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("signed audit time is unacceptably far in the future")
    if authorization_policy:
        _authorize(manifest, authorization_policy, verification_time, signed_at)
    return fingerprint


def _authorize(
    manifest: dict[str, object], policy_path: Path, now: datetime, signed_at: datetime
) -> None:
    policy = json.loads(policy_path.read_text("utf-8"))
    if (
        not isinstance(policy, dict)
        or set(policy) != {"schema_version", "trusted_signers"}
        or policy["schema_version"] != "1.0"
        or not isinstance(policy["trusted_signers"], list)
    ):
        raise ValueError("audit authorization policy is invalid")
    for signer in policy["trusted_signers"]:
        if not isinstance(signer, dict) or set(signer) != {
            "signer_id",
            "key_fingerprint",
            "purposes",
            "valid_from",
            "valid_until",
        }:
            raise ValueError("audit authorization signer entry is invalid")
        if (
            not isinstance(signer["signer_id"], str)
            or not signer["signer_id"].strip()
            or not isinstance(signer["key_fingerprint"], str)
            or not signer["key_fingerprint"].strip()
            or not isinstance(signer["purposes"], list)
            or not signer["purposes"]
            or any(not isinstance(item, str) or not item.strip() for item in signer["purposes"])
            or not isinstance(signer["valid_from"], str)
            or not isinstance(signer["valid_until"], str)
        ):
            raise ValueError("audit authorization signer entry is invalid")
        try:
            valid_from = datetime.fromisoformat(signer["valid_from"])
            valid_until = datetime.fromisoformat(signer["valid_until"])
        except ValueError as error:
            raise ValueError("audit authorization validity interval is invalid") from error
        if valid_from.tzinfo is None or valid_until.tzinfo is None or valid_until <= valid_from:
            raise ValueError("audit authorization validity interval is invalid")
        if (
            signer["signer_id"] == manifest["signer_id"]
            and signer["key_fingerprint"] == manifest["signer_key_fingerprint"]
            and isinstance(signer["purposes"], list)
            and manifest["purpose"] in signer["purposes"]
            and valid_from <= signed_at <= valid_until
            and valid_from <= now <= valid_until
        ):
            return
    raise ValueError("audit signer is not authorized by the supplied policy")
