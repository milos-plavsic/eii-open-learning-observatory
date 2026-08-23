import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from eii.appliance import (
    configured_tutor,
    create_package,
    verify_package,
)
from eii.appliance_package import safe_member_name, validate_unique_names
from eii.cli import main
from eii.crypto import sign_ed25519
from eii.domain import to_dict
from eii.persistence import open_existing_database
from eii.safety_reviews import sign_human_review, verify_human_review
from eii.safety_verification import authorize_safety_case
from eii.weather import WeatherStore


class HardeningV3Tests(unittest.TestCase):
    def keypair(self, root: Path) -> tuple[Path, Path]:
        private, public = root / "private.pem", root / "public.pem"
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

    def valid_manifest(self):
        return {
            "schema_version": "2.0",
            "package_id": "8a592bd1-4328-4ad8-8896-0873cf1b9737",
            "version": "1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": {"content/x": "sha256:" + hashlib.sha256(b"x").hexdigest()},
            "metadata": {},
        }

    def package_from_manifest(self, root, manifest, *, extra=False):
        raw = json.dumps(manifest, separators=(",", ":")).encode()
        package = root / "custom.eii"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("content/x", b"x")
            if extra:
                archive.writestr("content/extra", b"extra")
            archive.writestr("manifest.json", raw)
            archive.writestr("manifest.signature", sign_ed25519(raw, TEST_PRIVATE_KEY))
        return package

    def test_archive_path_and_creation_boundaries(self):
        for name in ("", "\\evil", "/evil", "a/../b", "a\n/b"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe"):
                safe_member_name(name)
        with self.assertRaisesRegex(ValueError, "too many"):
            validate_unique_names(["x"] * 10_003)
        with self.assertRaisesRegex(ValueError, "colliding"):
            validate_unique_names(["A", "a"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "x"
            file.write_text("x")
            link = root / "link"
            link.symlink_to(file)
            with self.assertRaisesRegex(ValueError, "symbolic"):
                create_package((link,), root / "p", version="1", private_key=TEST_PRIVATE_KEY)
            folder = root / "folder"
            folder.mkdir()
            (folder / "link").symlink_to(file)
            with self.assertRaisesRegex(ValueError, "symbolic"):
                create_package((folder,), root / "p", version="1", private_key=TEST_PRIVATE_KEY)
            (folder / "link").unlink()
            (folder / "nested").mkdir()
            with self.assertRaisesRegex(ValueError, "at least one"):
                create_package((folder,), root / "p", version="1", private_key=TEST_PRIVATE_KEY)
            for version in ("", "x" * 201):
                with self.assertRaisesRegex(ValueError, "version"):
                    create_package(
                        (file,), root / "p", version=version, private_key=TEST_PRIVATE_KEY
                    )
            with self.assertRaisesRegex(ValueError, "metadata"):
                create_package(
                    (file,),
                    root / "p",
                    version="1",
                    private_key=TEST_PRIVATE_KEY,
                    metadata={"x": "x" * 1_048_576},
                )

    def test_signed_manifest_semantic_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutations = (
                (lambda d: d.update(extra=True), "fields"),
                (lambda d: d.update(schema_version="1.0"), "schema version"),
                (lambda d: d.update(package_id="bad"), "identity"),
                (lambda d: d.update(created_at="2026-01-01"), "timezone"),
                (lambda d: d.update(metadata=[]), "timezone and files"),
                (lambda d: d["files"].update({"content/x": "bad"}), "hash declaration"),
            )
            for mutation, message in mutations:
                manifest = self.valid_manifest()
                mutation(manifest)
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    verify_package(
                        self.package_from_manifest(root, manifest), public_key=TEST_PUBLIC_KEY
                    )
            with self.assertRaisesRegex(ValueError, "exactly match"):
                verify_package(
                    self.package_from_manifest(root, self.valid_manifest(), extra=True),
                    public_key=TEST_PUBLIC_KEY,
                )
            raw = b'{"schema_version":"2.0","schema_version":"2.0"}'
            package = root / "duplicate.eii"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("manifest.json", raw)
                archive.writestr("manifest.signature", sign_ed25519(raw, TEST_PRIVATE_KEY))
            with self.assertRaisesRegex(ValueError, "duplicate manifest key"):
                verify_package(package, public_key=TEST_PUBLIC_KEY)
            raw = json.dumps(self.valid_manifest(), separators=(",", ":")).encode()
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("content/x", b"x")
                archive.writestr("manifest.json", raw)
                archive.writestr("manifest.signature", "hmac-sha256:unsupported")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                verify_package(package, public_key=TEST_PUBLIC_KEY)

    def test_archive_metadata_and_resource_rejections(self):
        info = MagicMock(filename="x", external_attr=(0o120777 << 16))
        archive = MagicMock()
        archive.__enter__.return_value.infolist.return_value = [info]
        with patch("eii.appliance_package.zipfile.ZipFile", return_value=archive):
            with self.assertRaisesRegex(ValueError, "symbolic"):
                verify_package(Path("x"), public_key=TEST_PUBLIC_KEY)
        cases = (
            ({"filename": "x", "external_attr": 0, "is_dir.return_value": True}, "oversized"),
            (
                {
                    "filename": "x",
                    "external_attr": 0,
                    "is_dir.return_value": False,
                    "file_size": 1,
                    "compress_size": 0,
                },
                "compressed size",
            ),
            (
                {
                    "filename": "x",
                    "external_attr": 0,
                    "is_dir.return_value": False,
                    "file_size": 1001,
                    "compress_size": 1,
                },
                "compression ratio",
            ),
        )
        for values, message in cases:
            item = MagicMock()
            for key, value in values.items():
                if key == "is_dir.return_value":
                    item.is_dir.return_value = value
                else:
                    setattr(item, key, value)
            item.file_size = getattr(item, "file_size", 0)
            item.compress_size = getattr(item, "compress_size", 1)
            mocked = MagicMock()
            mocked.__enter__.return_value.infolist.return_value = [item]
            with patch("eii.appliance_package.zipfile.ZipFile", return_value=mocked):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    verify_package(Path("x"), public_key=TEST_PUBLIC_KEY)
        normal = MagicMock(
            filename="x", external_attr=0, file_size=2_147_483_649, compress_size=3_000_000
        )
        normal.is_dir.return_value = False
        mocked = MagicMock()
        mocked.__enter__.return_value.infolist.return_value = [normal]
        with (
            patch("eii.appliance_package.MAX_MEMBER_BYTES", 3_000_000_000),
            patch("eii.appliance_package.zipfile.ZipFile", return_value=mocked),
        ):
            with self.assertRaisesRegex(ValueError, "2 GiB"):
                verify_package(Path("x"), public_key=TEST_PUBLIC_KEY)

    def test_human_review_signatures_and_operator_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, public = self.keypair(root)
            for values, message in (
                (("", "r", "why", "2026-01-01T00:00:00+00:00"), "non-empty"),
                (("f", "r", "why", "invalid"), "time is invalid"),
                (("f", "r", "why", "2026-01-01"), "timezone"),
            ):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    sign_human_review(
                        fixture_id=values[0],
                        subject_hash="sha256:" + "a" * 64,
                        reviewer=values[1],
                        approved=True,
                        rationale=values[2],
                        created_at=values[3],
                        private_key=private,
                        public_key=public,
                    )
            review = sign_human_review(
                fixture_id="f",
                subject_hash="sha256:" + "a" * 64,
                reviewer="r",
                approved=True,
                rationale="why",
                created_at="2026-01-01T00:00:00+00:00",
                private_key=private,
                public_key=public,
            )
            verify_human_review(review)
            broken = to_dict(review)
            broken["reviewer_key_fingerprint"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                verify_human_review(broken)
            broken = to_dict(review)
            broken["rationale"] = "changed"
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_human_review(broken)
            with self.assertRaisesRegex(ValueError, "signed payload"):
                verify_human_review({})
            document = {
                "release_decision": "configured_gates_passed",
                "human_evaluations": [to_dict(review)],
            }
            with self.assertRaisesRegex(ValueError, "trust policy"):
                authorize_safety_case(document)
            authorize_safety_case(
                document, trusted_reviewer_fingerprints=frozenset({review.reviewer_key_fingerprint})
            )

    def test_privacy_rotation_ledger_and_cli(self):
        secret = b"a" * 32
        ledger = b"l" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "weather.db"
            with WeatherStore(database, secret=secret, ledger_key=ledger) as store:
                self.assertIsNone(store.verify_export_ledger())
                store.export(root / "one.json", now=datetime.now(UTC))
                self.assertIsNotNone(store.verify_export_ledger())
                with self.assertRaises(sqlite3.IntegrityError):
                    store.connection.execute("DELETE FROM privacy_export_audit")
                store.connection.execute("DROP TRIGGER privacy_export_audit_no_update")
                store.connection.execute(
                    "UPDATE privacy_export_audit SET record_hash=?", ("0" * 64,)
                )
                store.connection.commit()
                with self.assertRaisesRegex(ValueError, "authentication"):
                    store.verify_export_ledger()
                with self.assertRaisesRegex(ValueError, "32 bytes"):
                    store.rotate_privacy_key(new_secret=b"short", new_epoch="v2")
                with self.assertRaisesRegex(ValueError, "both be new"):
                    store.rotate_privacy_key(new_secret=secret, new_epoch="v1")
            with self.assertRaisesRegex(ValueError, "explicit"):
                WeatherStore(database, secret=b"z" * 32, ledger_key=ledger, key_epoch="v2")
            with self.assertRaisesRegex(ValueError, "ledger key"):
                WeatherStore(root / "short-ledger.db", secret=secret, ledger_key=b"short")
            chain_db = root / "chain.db"
            with WeatherStore(chain_db, secret=secret, ledger_key=ledger) as store:
                now = datetime.now(UTC)
                store.export(root / "a.json", now=now)
                store.export(root / "b.json", now=now)
                store.connection.execute("DROP TRIGGER privacy_export_audit_no_update")
                store.connection.execute(
                    "UPDATE privacy_export_audit SET previous_hash='broken' WHERE sequence=2"
                )
                store.connection.commit()
                with self.assertRaisesRegex(ValueError, "discontinuous"):
                    store.verify_export_ledger()
            generated = root / "generated"
            self.assertEqual(main(["weather-key-generate", "--output", str(generated)]), 0)
            self.assertEqual(len(generated.read_text().strip()), 64)
            self.assertEqual(generated.stat().st_mode & 0o777, 0o600)
            current_file, new_file, ledger_file = (
                root / "current",
                root / "new",
                root / "ledger",
            )
            for path, value in (
                (current_file, b"c" * 32),
                (new_file, b"n" * 32),
                (ledger_file, b"k" * 32),
            ):
                path.write_bytes(value)
                path.chmod(0o600)
            rotation_db = root / "rotation.db"
            WeatherStore(
                rotation_db, secret=b"c" * 32, ledger_key=b"k" * 32, key_epoch="one"
            ).close()
            self.assertEqual(
                main(
                    [
                        "weather-key-rotate",
                        "--database",
                        str(rotation_db),
                        "--current-secret-file",
                        str(current_file),
                        "--new-secret-file",
                        str(new_file),
                        "--ledger-key-file",
                        str(ledger_file),
                        "--current-epoch",
                        "one",
                        "--new-epoch",
                        "two",
                        "--backup",
                        str(root / "rotation-backup.db"),
                    ]
                ),
                0,
            )

    def test_human_review_signing_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, public = self.keypair(root)
            unsigned = root / "unsigned.json"
            case = root / "case.json"
            case.write_text(json.dumps({"cases": [{"fixture": {"id": "f"}, "passed": True}]}))
            self.assertEqual(
                main(
                    [
                        "safety-review-init",
                        str(case),
                        "--fixture-id",
                        "f",
                        "--reviewer",
                        "r",
                        "--decision",
                        "approve",
                        "--rationale",
                        "reviewed",
                        "--output",
                        str(unsigned),
                    ]
                ),
                0,
            )
            with self.assertRaises(SystemExit):
                main(
                    [
                        "safety-review-init",
                        str(case),
                        "--fixture-id",
                        "missing",
                        "--reviewer",
                        "r",
                        "--decision",
                        "reject",
                        "--rationale",
                        "none",
                        "--output",
                        str(unsigned),
                    ]
                )
            output = root / "signed.json"
            self.assertEqual(
                main(
                    [
                        "safety-review-sign",
                        str(unsigned),
                        "--private-key-file",
                        str(private),
                        "--public-key-file",
                        str(public),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            verify_human_review(json.loads(output.read_text()))
            unsigned.write_text("{}")
            with self.assertRaises(SystemExit):
                main(
                    [
                        "safety-review-sign",
                        str(unsigned),
                        "--private-key-file",
                        str(private),
                        "--public-key-file",
                        str(public),
                        "--output",
                        str(output),
                    ]
                )

    def test_maintenance_open_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                open_existing_database(root / "missing", kind="weather")
            database = root / "x.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE _eii_database(kind TEXT)")
            connection.execute("INSERT INTO _eii_database VALUES ('other')")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "identity"):
                open_existing_database(database, kind="weather")
            mocked = MagicMock()
            mocked.execute.return_value.fetchone.side_effect = [("weather",), ("corrupt",)]
            with patch("eii.persistence.sqlite3.connect", return_value=mocked):
                with self.assertRaisesRegex(ValueError, "integrity"):
                    open_existing_database(database, kind="weather")
            mocked.close.assert_called_once()

    def test_configured_tutor_rejects_path_and_unknown_course(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "releases" / "p"
            release.mkdir(parents=True)
            (root / "active.json").write_text('{"package_id":"p","version":"1"}')
            for course_path, message in (("../x", "unsafe"), ("content/x", "compatible")):
                (release / "manifest.json").write_text(
                    json.dumps(
                        {
                            "metadata": {
                                "model_base_url": "http://localhost",
                                "model": "m",
                                "course_path": course_path,
                            }
                        }
                    )
                )
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    configured_tutor(root)


if __name__ == "__main__":
    unittest.main()
