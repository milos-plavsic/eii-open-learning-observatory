"""Central Ed25519 operations for signed evidence and appliance releases."""

from __future__ import annotations

import base64
import re
import shutil

# Calls use a resolved executable, fixed argv, and no shell.
import subprocess  # nosec B404
import tempfile
from functools import cache
from pathlib import Path

from .secureio import require_private_file

SIGNATURE_PREFIX = "ed25519:"
OPENSSL = shutil.which("openssl")
_SELF_TEST_PAYLOAD = b"EII OpenSSL Ed25519 self-test v1"
_SELF_TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIBQjXMacxw4wTXCFh4yub+tVH+N4EVuU6GDNOs7I2kCP
-----END PRIVATE KEY-----
"""
_SELF_TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAS4vtWiHrL0XSfzO65IEs3t4qXXmpiCpsEpUSUW5V7nk=
-----END PUBLIC KEY-----
"""
_SELF_TEST_SIGNATURE = base64.b64decode(
    "RCdfVQQ7z0MaVEvtL22TEee1UgV8JbYLGIfgQ4c1u54JeAUoYJKoQncqXENzWtduddSnEjN5tZBy4QD72Am3Bg=="
)


class CryptoError(ValueError):
    """A key, signature, or cryptographic operation is invalid."""


def _key(path: Path | None, kind: str) -> Path:
    if path is None or not path.is_file():
        raise CryptoError(f"Ed25519 {kind} key is missing")
    if kind == "private":
        try:
            require_private_file(path, label="Ed25519 private key")
        except ValueError as error:
            raise CryptoError(str(error)) from error
    return path


def _openssl_path() -> str:
    if OPENSSL is None:
        raise CryptoError("OpenSSL executable is unavailable")
    return OPENSSL


@cache
def _probe_openssl(executable: str) -> str:
    process = subprocess.run([executable, "version"], capture_output=True, check=False)  # nosec B603
    output = process.stdout.decode(errors="replace").strip()
    match = re.match(r"OpenSSL\s+(\d+)\.(\d+)", output)
    if process.returncode or match is None or int(match.group(1)) < 3:
        detail = (process.stderr.decode(errors="replace").strip() or output)[:300]
        raise CryptoError(
            "OpenSSL 3 or newer with Ed25519 pkeyutl support is required"
            + (f": {detail}" if detail else "")
        )
    return output


def openssl_version() -> str:
    """Return the validated OpenSSL runtime identity or fail closed."""
    return _probe_openssl(_openssl_path())


@cache
def crypto_self_test() -> None:
    """Fail closed unless OpenSSL reproduces and verifies a fixed Ed25519 vector."""
    executable = _openssl_path()
    _probe_openssl(executable)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        private_key, public_key = root / "private.pem", root / "public.pem"
        payload, signature = root / "payload", root / "signature"
        private_key.write_text(_SELF_TEST_PRIVATE_KEY, "ascii")
        public_key.write_text(_SELF_TEST_PUBLIC_KEY, "ascii")
        payload.write_bytes(_SELF_TEST_PAYLOAD)
        signature.write_bytes(_SELF_TEST_SIGNATURE)
        signed = subprocess.run(
            [
                executable,
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(private_key),
                "-in",
                str(payload),
            ],
            capture_output=True,
            check=False,
        )  # nosec B603
        verified = subprocess.run(
            [
                executable,
                "pkeyutl",
                "-verify",
                "-rawin",
                "-pubin",
                "-inkey",
                str(public_key),
                "-in",
                str(payload),
                "-sigfile",
                str(signature),
            ],
            capture_output=True,
            check=False,
        )  # nosec B603
    if signed.returncode or signed.stdout != _SELF_TEST_SIGNATURE or verified.returncode:
        raise CryptoError("OpenSSL Ed25519 behavioral self-test failed")


def _openssl() -> str:
    executable = _openssl_path()
    _probe_openssl(executable)
    return executable


def sign_ed25519(data: bytes, private_key: Path | None) -> str:
    key = _key(private_key, "private")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "payload"
        source.write_bytes(data)
        process = subprocess.run(
            [_openssl(), "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(source)],
            capture_output=True,
            check=False,
        )  # nosec B603
    if process.returncode:
        detail = process.stderr.decode(errors="replace").strip()
        raise CryptoError(f"Ed25519 signing failed{': ' + detail if detail else ''}")
    return SIGNATURE_PREFIX + base64.b64encode(process.stdout).decode("ascii")


def verify_ed25519(data: bytes, signature: str, public_key: Path | None) -> bool:
    if public_key is None or not public_key.is_file() or not signature.startswith(SIGNATURE_PREFIX):
        return False
    try:
        raw = base64.b64decode(signature.removeprefix(SIGNATURE_PREFIX), validate=True)
    except ValueError:
        return False
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "payload"
        signature_file = Path(directory) / "signature"
        source.write_bytes(data)
        signature_file.write_bytes(raw)
        process = subprocess.run(
            [
                _openssl(),
                "pkeyutl",
                "-verify",
                "-rawin",
                "-pubin",
                "-inkey",
                str(public_key),
                "-in",
                str(source),
                "-sigfile",
                str(signature_file),
            ],
            capture_output=True,
            check=False,
        )  # nosec B603
    return process.returncode == 0


def public_key_fingerprint(public_key: Path) -> str:
    key = _key(public_key, "public")
    process = subprocess.run(
        [_openssl(), "pkey", "-pubin", "-in", str(key), "-outform", "DER"],
        capture_output=True,
        check=False,
    )  # nosec B603
    if process.returncode:
        raise CryptoError("invalid Ed25519 public key")
    from hashlib import sha256

    return sha256(process.stdout).hexdigest()


def public_key_fingerprint_pem(public_key_pem: str) -> str:
    """Fingerprint an embedded PEM key without treating its display name as identity."""
    with tempfile.TemporaryDirectory() as directory:
        key = Path(directory) / "public.pem"
        key.write_text(public_key_pem, encoding="utf-8")
        return public_key_fingerprint(key)


def verify_ed25519_pem(data: bytes, signature: str, public_key_pem: str) -> bool:
    """Verify against an embedded public key while retaining the central crypto policy."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as key:
        key.write(public_key_pem)
        key_path = Path(key.name)
    try:
        return verify_ed25519(data, signature, key_path)
    finally:
        key_path.unlink(missing_ok=True)
