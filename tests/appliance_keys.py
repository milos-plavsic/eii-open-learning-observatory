"""Process-local asymmetric keys for appliance unit tests."""

from __future__ import annotations

import atexit
import subprocess
import tempfile
from pathlib import Path


def generate_keypair(root: Path, prefix: str = "test") -> tuple[Path, Path]:
    private = root / f"{prefix}-private.pem"
    public = root / f"{prefix}-public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


_KEY_DIRECTORY = tempfile.TemporaryDirectory()
atexit.register(_KEY_DIRECTORY.cleanup)
TEST_PRIVATE_KEY, TEST_PUBLIC_KEY = generate_keypair(Path(_KEY_DIRECTORY.name))
