import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.crypto import CryptoError, sign_ed25519
from eii.secureio import read_secret_bytes, require_private_file, write_private_text


class SecureIoTests(unittest.TestCase):
    def test_private_read_write_permissions_and_lengths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nested/secret"
            write_private_text(path, "secret\n")
            self.assertEqual(read_secret_bytes(path, label="token", minimum_bytes=6), b"secret")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(ValueError, "at least 7"):
                read_secret_bytes(path, label="token", minimum_bytes=7)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "group or other"):
                require_private_file(path, label="token")
            with self.assertRaisesRegex(CryptoError, "group or other"):
                sign_ed25519(b"x", path)
            with self.assertRaisesRegex(ValueError, "missing"):
                require_private_file(root / "missing", label="token")

    def test_windows_does_not_treat_compatibility_mode_as_a_posix_acl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("secret", encoding="utf-8")
            path.chmod(0o666)
            with patch("eii.secureio.os.name", "nt"):
                require_private_file(path, label="token")


if __name__ == "__main__":
    unittest.main()
