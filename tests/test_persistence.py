import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eii.persistence import backup_database, connect_database, database_status
from eii.study import ReviewStudy
from eii.weather import WeatherStore


class PersistenceTests(unittest.TestCase):
    def test_configuration_version_identity_and_failed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, migrations in (("", ("SELECT 1;",)), ("x", ())):
                with self.assertRaises(ValueError):
                    connect_database(root / "invalid.db", kind=kind, migrations=migrations)
            future = root / "future.db"
            connection = sqlite3.connect(future)
            connection.execute("PRAGMA user_version=9")
            connection.close()
            with self.assertRaisesRegex(ValueError, "newer than supported"):
                connect_database(future, kind="x", migrations=("SELECT 1;",))
            first = connect_database(root / "kind.db", kind="first", migrations=("SELECT 1;",))
            first.close()
            with self.assertRaisesRegex(ValueError, "not second"):
                connect_database(root / "kind.db", kind="second", migrations=("SELECT 1;",))
            with self.assertRaises(sqlite3.OperationalError):
                connect_database(root / "broken.db", kind="x", migrations=("INVALID SQL;",))

    def test_store_status_pragmas_backup_and_identity_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with WeatherStore(
                root / "weather.db", secret=b"0123456789abcdef0123456789abcdef"
            ) as weather:
                status = weather.status()
                self.assertEqual(
                    (status.kind, status.schema_version, status.integrity), ("weather", 5, "ok")
                )
                self.assertEqual(
                    weather.connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
                weather.backup(root / "nested" / "weather-backup.db")
                with self.assertRaisesRegex(ValueError, "identity"):
                    database_status(weather.connection, kind="other")
            with WeatherStore(
                root / "nested" / "weather-backup.db", secret=b"0123456789abcdef0123456789abcdef"
            ) as restored:
                self.assertEqual(restored.status().integrity, "ok")
            with ReviewStudy(root / "study.db") as study:
                self.assertEqual(study.status().kind, "review-study")
                study.backup(root / "study-backup.db")
            with ReviewStudy(root / "study-backup.db") as restored:
                self.assertEqual(restored.status().schema_version, 1)

    def test_integrity_failures_close_connection_and_reject_backup(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("corrupt",)
        with patch("eii.persistence.sqlite3.connect", return_value=connection):
            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                connect_database(Path("x"), kind="x", migrations=("SELECT 1;",))
        connection.close.assert_called_once()
        source = MagicMock()
        backup = MagicMock()
        backup.__enter__.return_value = backup
        backup.execute.return_value.fetchone.return_value = ("corrupt",)
        with patch("eii.persistence.sqlite3.connect", return_value=backup):
            with self.assertRaisesRegex(ValueError, "backup integrity"):
                backup_database(source, Path("backup"))


if __name__ == "__main__":
    unittest.main()
