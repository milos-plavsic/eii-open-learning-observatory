import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eii.crypto import (
    CryptoError,
    _probe_openssl,
    crypto_self_test,
    openssl_version,
    public_key_fingerprint,
    sign_ed25519,
    verify_ed25519,
)


class CryptoTests(unittest.TestCase):
    def test_missing_keys_and_invalid_signature_are_rejected(self):
        with self.assertRaisesRegex(CryptoError, "private key is missing"):
            sign_ed25519(b"data", Path("missing"))
        with self.assertRaisesRegex(CryptoError, "public key is missing"):
            public_key_fingerprint(Path("missing"))
        self.assertFalse(verify_ed25519(b"data", "bad", None))

    def test_empty_openssl_error_is_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("bad")
            key.chmod(0o600)
            result = MagicMock(returncode=1, stderr=b"", stdout=b"")
            with (
                patch("eii.crypto._probe_openssl", return_value="OpenSSL 3.0.0"),
                patch("eii.crypto.subprocess.run", return_value=result),
            ):
                with self.assertRaisesRegex(CryptoError, "Ed25519 signing failed$"):
                    sign_ed25519(b"data", key)

    def test_missing_openssl_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("key")
            key.chmod(0o600)
            with (
                patch("eii.crypto.OPENSSL", None),
                self.assertRaisesRegex(CryptoError, "unavailable"),
            ):
                sign_ed25519(b"data", key)

    def test_openssl_runtime_requires_supported_version(self):
        _probe_openssl.cache_clear()
        supported = MagicMock(returncode=0, stdout=b"OpenSSL 3.5.0 1 Jan 2026", stderr=b"")
        with (
            patch("eii.crypto.OPENSSL", "/test/openssl"),
            patch("eii.crypto.subprocess.run", return_value=supported),
        ):
            self.assertEqual(openssl_version(), "OpenSSL 3.5.0 1 Jan 2026")
        for executable, result in (
            ("/test/libressl", MagicMock(returncode=0, stdout=b"LibreSSL 4.0", stderr=b"")),
            ("/test/old", MagicMock(returncode=0, stdout=b"OpenSSL 1.1.1", stderr=b"")),
            ("/test/broken", MagicMock(returncode=1, stdout=b"", stderr=b"broken")),
        ):
            with (
                self.subTest(executable=executable),
                patch("eii.crypto.subprocess.run", return_value=result),
                self.assertRaisesRegex(CryptoError, "OpenSSL 3 or newer"),
            ):
                _probe_openssl(executable)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_real_sign_verify_fingerprint_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.pem"
            public = root / "public.pem"
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
            signature = sign_ed25519(b"data", private)
            self.assertTrue(verify_ed25519(b"data", signature, public))
            self.assertFalse(verify_ed25519(b"tampered", signature, public))
            self.assertEqual(len(public_key_fingerprint(public)), 64)
            self.assertRegex(openssl_version(), r"^OpenSSL (?:[3-9]|[1-9]\d+)\.")
            crypto_self_test.cache_clear()
            crypto_self_test()
            crypto_self_test.cache_clear()
            failed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"bad")
            with (
                patch("eii.crypto.subprocess.run", return_value=failed),
                self.assertRaisesRegex(CryptoError, "self-test failed"),
            ):
                crypto_self_test()
            crypto_self_test.cache_clear()


if __name__ == "__main__":
    unittest.main()
