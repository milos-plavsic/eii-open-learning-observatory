import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.adapters import PlctExportAdapter
from eii.cli import main
from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind
from eii.plct_conformance import (
    compare_plct_exports,
    create_conformance_attestation,
    evaluate_plct_export,
    verify_conformance_attestation,
    write_conformance_report,
)


def base_document(version="1"):
    return {
        "format": "plct-course-export-v1",
        "course_key": "course",
        "canonical_course_id": "course",
        "repository": "petlja/course",
        "language": "en",
        "version": version,
        "activities": [{"activity_key": "a", "title": "Activity", "text": "Evidence"}],
    }


def write_document(root: Path, document, name="export.json") -> Path:
    path = root / name
    path.write_text(json.dumps(document))
    return path


def conforming_document(root: Path, *, attested=False):
    document = base_document()
    path = write_document(root, document)
    block = PlctExportAdapter().load(path).blocks[0]
    document["query_context_cases"] = [
        {
            "id": "q1",
            "question": "What is the evidence?",
            "activity_key": "a",
            "retrieved": [{"block_id": block.id, "block_hash": block.hash, "score": 0.9}],
        }
    ]
    if attested:
        document["petlja_attestation"] = {
            "maintainer": "petlja-reviewer",
            "reviewed_at": "2026-08-21",
        }
    return document


class PlctConformanceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_signed_external_attestation_binding_and_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = write_document(root, conforming_document(root))
            report_path = root / "report.json"
            write_conformance_report(evaluate_plct_export(export), report_path)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True
            )
            attestation = root / "attestation.json"
            self.assertEqual(
                main(
                    [
                        "plct-attest",
                        str(report_path),
                        "--maintainer",
                        "Petlja maintainer",
                        "--repository-revision",
                        "abc",
                        "--private-key-file",
                        str(private),
                        "--public-key-file",
                        str(public),
                        "--output",
                        str(attestation),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "plct-attestation-verify",
                        str(attestation),
                        "--report",
                        str(report_path),
                        "--public-key-file",
                        str(public),
                    ]
                ),
                0,
            )
            with self.assertRaisesRegex(ValueError, "required"):
                create_conformance_attestation(
                    report_path,
                    root / "x",
                    maintainer="",
                    repository_revision="abc",
                    private_key=private,
                    public_key=public,
                )
            with (
                patch("eii.plct_conformance.verify_ed25519", return_value=False),
                self.assertRaisesRegex(ValueError, "do not match"),
            ):
                create_conformance_attestation(
                    report_path,
                    root / "x",
                    maintainer="m",
                    repository_revision="abc",
                    private_key=private,
                    public_key=public,
                )
            incompatible = json.loads(report_path.read_text())
            incompatible["compatible"] = False
            from eii.domain import content_hash

            incompatible["report_hash"] = content_hash(
                {key: value for key, value in incompatible.items() if key != "report_hash"}
            )
            incompatible_path = root / "incompatible.json"
            incompatible_path.write_text(json.dumps(incompatible))
            with self.assertRaisesRegex(ValueError, "compatible canonical"):
                create_conformance_attestation(
                    incompatible_path,
                    root / "x",
                    maintainer="m",
                    repository_revision="abc",
                    private_key=private,
                    public_key=public,
                )
            original_report = report_path.read_text()
            report = json.loads(original_report)
            report["compatible"] = False
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "report hash"):
                create_conformance_attestation(
                    report_path,
                    root / "x",
                    maintainer="m",
                    repository_revision="abc",
                    private_key=private,
                    public_key=public,
                )
            report_path.write_text(original_report)
            original_attestation = attestation.read_text()
            document = json.loads(original_attestation)
            document["id"] = "bad"
            attestation.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "id is invalid"):
                verify_conformance_attestation(attestation, report_path, public)
            document = json.loads(original_attestation)
            document["key_fingerprint"] = "bad"
            attestation.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                verify_conformance_attestation(attestation, report_path, public)
            document = json.loads(original_attestation)
            document["signature"] = "bad"
            attestation.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_conformance_attestation(attestation, report_path, public)
            attestation.write_text(original_attestation)
            report = json.loads(original_report)
            report["report_hash"] = "bad"
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "not bound"):
                verify_conformance_attestation(attestation, report_path, public)

    def test_conforming_export_report_attestation_and_cli_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = write_document(root, conforming_document(root), "current.json")
            report = evaluate_plct_export(current)
            self.assertTrue(report.compatible)
            self.assertIsNone(report.external_attestation)
            attested = write_document(
                root, conforming_document(root, attested=True), "attested.json"
            )
            self.assertIsNotNone(evaluate_plct_export(attested).external_attestation)
            previous_document = conforming_document(root)
            previous_document["version"] = "0"
            previous = write_document(root, previous_document, "previous.json")
            output = root / "reports" / "conformance.json"
            self.assertEqual(
                main(
                    [
                        "plct-conformance",
                        str(current),
                        "--previous",
                        str(previous),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertIn("report_hash", json.loads(output.read_text()))
            compatibility = json.loads(
                (root / "reports/conformance-compatibility.json").read_text()
            )
            self.assertEqual(compatibility["stable_ids"], ["plct:course:a"])

    def test_invalid_export_and_every_query_context_failure_are_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scalar = root / "scalar.json"
            scalar.write_text("[]")
            self.assertFalse(evaluate_plct_export(scalar).compatible)
            malformed = root / "malformed.json"
            malformed.write_text("{")
            self.assertFalse(evaluate_plct_export(malformed).compatible)
            missing_cases = write_document(root, base_document(), "missing.json")
            self.assertFalse(evaluate_plct_export(missing_cases).compatible)
            document = conforming_document(root)
            valid = document["query_context_cases"][0]
            document["query_context_cases"] = [
                "bad",
                {**valid, "id": ""},
                valid,
                {**valid, "id": "q1", "question": "", "activity_key": "missing"},
                {**valid, "id": "empty", "retrieved": []},
                {
                    **valid,
                    "id": "items",
                    "retrieved": [
                        "bad",
                        {"block_id": "missing", "block_hash": "bad", "score": True},
                        {
                            "block_id": valid["retrieved"][0]["block_id"],
                            "block_hash": valid["retrieved"][0]["block_hash"],
                            "score": float("inf"),
                        },
                    ],
                },
            ]
            path = write_document(root, document, "invalid-cases.json")
            report = evaluate_plct_export(path)
            self.assertFalse(report.compatible)
            detail = next(
                check.detail for check in report.checks if check.name == "query-context-fixtures"
            )
            self.assertIn("duplicated", detail)
            self.assertIn("invalid score", detail)
            output = root / "report.json"
            self.assertEqual(main(["plct-conformance", str(path), "--output", str(output)]), 2)

    def test_adapter_invariant_failure_and_cross_course_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_document(root, base_document())
            locator = SourceLocator("bad", "bad", "wrong")
            block = ContentBlock("wrong", UnitKind.ACTIVITY, "x", "x", 1, locator)
            release = CourseRelease(
                "r", "course", "en", "1", "c", (block,), locator, canonical_course_id="course"
            )
            with patch("eii.plct_conformance.PlctExportAdapter.load", return_value=release):
                self.assertFalse(
                    next(
                        c
                        for c in evaluate_plct_export(source).checks
                        if c.name == "stable-identifiers"
                    ).passed
                )
            other = base_document()
            other["canonical_course_id"] = "other"
            other_path = write_document(root, other, "other.json")
            with self.assertRaisesRegex(ValueError, "same canonical"):
                compare_plct_exports(source, other_path)

    def test_write_report_creates_parent_and_change_sets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = base_document("1")
            after = base_document("2")
            after["activities"][0]["text"] = "Changed"
            after["activities"].append({"activity_key": "b", "text": "new"})
            before["activities"].append({"activity_key": "removed", "text": "old"})
            previous = write_document(root, before, "before.json")
            current = write_document(root, after, "after.json")
            comparison = compare_plct_exports(previous, current)
            self.assertEqual(comparison["added_ids"], ["plct:course:b"])
            self.assertEqual(comparison["removed_ids"], ["plct:course:removed"])
            self.assertEqual(comparison["changed_ids"], ["plct:course:a"])
            report = evaluate_plct_export(current)
            destination = root / "nested/report.json"
            write_conformance_report(report, destination)
            self.assertTrue(destination.exists())


if __name__ == "__main__":
    unittest.main()
