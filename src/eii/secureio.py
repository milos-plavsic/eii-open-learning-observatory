"""Fail-closed local secret-file reads and private artifact writes."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def require_private_file(path: Path, *, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} file is missing")
    # ``st_mode`` exposes the owning process' Windows compatibility mask, not
    # the file's discretionary ACL.  Treating those synthesized group/other
    # bits as POSIX permissions rejects normally protected Windows key files.
    # Windows access control remains the responsibility of the file's DACL;
    # POSIX permission bits are enforced everywhere they are authoritative.
    if os.name == "nt":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError(f"{label} file must not be accessible by group or other users")


def read_secret_bytes(path: Path, *, label: str, minimum_bytes: int = 1) -> bytes:
    require_private_file(path, label=label)
    value = path.read_bytes().strip()
    if len(value) < minimum_bytes:
        raise ValueError(f"{label} must contain at least {minimum_bytes} bytes")
    return value


def write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
    path.chmod(0o600)
