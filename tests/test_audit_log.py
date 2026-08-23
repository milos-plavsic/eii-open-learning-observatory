import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.audit_log import ManagedAuditLog


class ManagedAuditLogTests(unittest.TestCase):
    def test_rotates_privately_and_purges_expired_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "audit.jsonl"
            expired = root / "audit.jsonl.old.jsonl"
            expired.write_text("old")
            os.utime(expired, (1, 1))
            with ManagedAuditLog(path, max_bytes=1024, retention_days=1) as stream:
                stream.write("x" * 900)
                stream.write("y" * 200)
                stream.flush()
            self.assertFalse(expired.exists())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(root.glob("audit.jsonl.*.jsonl"))), 1)

    def test_rejects_unsafe_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "limits"):
                ManagedAuditLog(Path(directory) / "a", max_bytes=1)
            with self.assertRaisesRegex(ValueError, "limits"):
                ManagedAuditLog(Path(directory) / "a", retention_days=0)

    def test_rejects_symlinks_oversized_records_and_concurrent_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises((OSError, ValueError)):
                ManagedAuditLog(link)
            path = root / "audit.jsonl"
            with ManagedAuditLog(path, max_bytes=1024) as stream:
                with self.assertRaisesRegex(ValueError, "one audit record"):
                    stream.write("x" * 1025)
                with self.assertRaisesRegex(ValueError, "already has a writer"):
                    ManagedAuditLog(path)
                stream._next_purge_at = 0
                stream.write("ok\n")
            with self.assertRaisesRegex(ValueError, "closed"):
                stream.write("late")
            stream.close()

            unsafe = root / "unsafe.jsonl"
            with patch("eii.audit_log.stat.S_ISREG", return_value=False):
                with self.assertRaisesRegex(ValueError, "unsafe lock"):
                    ManagedAuditLog(unsafe)

            instance = ManagedAuditLog.__new__(ManagedAuditLog)
            instance.path = root / "stream.jsonl"
            with patch("eii.audit_log.stat.S_ISREG", return_value=False):
                with self.assertRaisesRegex(ValueError, "regular non-symbolic"):
                    instance._open_stream()


if __name__ == "__main__":
    unittest.main()
