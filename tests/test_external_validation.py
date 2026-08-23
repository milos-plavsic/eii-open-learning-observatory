import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.cli import main
from eii.external_validation import sign_external_record, verify_external_record


def statement():
    return {
        "schema_version": "1.0",
        "gate_type": "penetration-test",
        "executed_at": "2026-08-21T12:00:00+00:00",
        "organization": "Independent lab",
        "reviewer": "reviewer",
        "scope": "release",
        "procedure_version": "1",
        "subject_hashes": ["sha256:" + "0" * 64],
        "outcome": "passed",
        "findings": [],
        "limitations": [],
    }


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
class ExternalValidationTests(unittest.TestCase):
    def test_sign_verify_cli_and_tamper_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "statement.json"
            source.write_text(json.dumps(statement()))
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True
            )
            record = root / "nested/record.json"
            self.assertEqual(
                main(
                    [
                        "external-record-sign",
                        str(source),
                        "--private-key-file",
                        str(private),
                        "--public-key-file",
                        str(public),
                        "--output",
                        str(record),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(["external-record-verify", str(record), "--public-key-file", str(public)]), 0
            )
            original = record.read_text()
            document = json.loads(original)
            malformed = root / "malformed.json"
            malformed.write_text("[]")
            with self.assertRaisesRegex(ValueError, "record fields"):
                verify_external_record(malformed, public)
            document["extra"] = True
            record.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "record fields"):
                verify_external_record(record, public)
            document = json.loads(original)
            document["statement"] = []
            record.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "statement fields"):
                verify_external_record(record, public)
            document = json.loads(original)
            document["id"] = "bad"
            record.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "id is invalid"):
                verify_external_record(record, public)
            document = json.loads(original)
            document["key_fingerprint"] = "bad"
            record.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                verify_external_record(record, public)
            document = json.loads(original)
            document["signature"] = "bad"
            record.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "signature verification"):
                verify_external_record(record, public)

    def test_signing_rejects_every_invalid_statement_and_key_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True
            )
            source = root / "statement.json"
            for value, message in (
                ([], "statement fields"),
                ({**statement(), "extra": 1}, "statement fields"),
                ({**statement(), "schema_version": "2"}, "schema version"),
                ({**statement(), "gate_type": "unknown"}, "gate type"),
                ({**statement(), "outcome": "unknown"}, "outcome"),
                ({**statement(), "subject_hashes": []}, "subject hashes"),
            ):
                source.write_text(json.dumps(value))
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    sign_external_record(
                        source, root / "record", private_key=private, public_key=public
                    )
            source.write_text(json.dumps(statement()))
            with (
                patch("eii.external_validation.verify_ed25519", return_value=False),
                self.assertRaisesRegex(ValueError, "do not match"),
            ):
                sign_external_record(
                    source, root / "record", private_key=private, public_key=public
                )


if __name__ == "__main__":
    unittest.main()
