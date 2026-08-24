import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from eii import __version__
from eii.release_preflight import (
    artifact_version,
    require_clean_source_tree,
    validate_attestation_receipt,
    validate_release_candidate,
    write_approval_evidence,
)


class ReleasePreflightTests(unittest.TestCase):
    def test_attestation_receipt_validation_is_fail_closed(self):
        predicate = "https://slsa.dev/provenance/v1"
        digest = "a" * 64

        def receipt():
            return [
                {
                    "verificationResult": {
                        "statement": {
                            "predicateType": predicate,
                            "subject": [{"digest": {"sha256": digest}}],
                        },
                        "verifiedTimestamps": [{}],
                        "signature": {"certificate": {}},
                    }
                }
            ]

        validate_attestation_receipt(receipt(), predicate_type=predicate, artifact_hashes={digest})
        for malformed in ({}, [], [None], [{"verificationResult": None}]):
            with self.assertRaisesRegex(ValueError, "verified results|result is invalid"):
                validate_attestation_receipt(
                    malformed, predicate_type=predicate, artifact_hashes={digest}
                )

        for mutate in (
            lambda item: item["verificationResult"].pop("statement"),
            lambda item: item["verificationResult"]["statement"].update(
                {"predicateType": "unexpected"}
            ),
            lambda item: item["verificationResult"]["statement"].update({"subject": {}}),
            lambda item: item["verificationResult"].update({"verifiedTimestamps": []}),
            lambda item: item["verificationResult"].update({"signature": None}),
            lambda item: item["verificationResult"]["signature"].update({"certificate": None}),
        ):
            document = receipt()
            mutate(document[0])
            with self.assertRaisesRegex(ValueError, "incomplete"):
                validate_attestation_receipt(
                    document, predicate_type=predicate, artifact_hashes={digest}
                )

        for subject in (None, {"digest": None}, {"digest": {"sha256": None}}):
            document = receipt()
            document[0]["verificationResult"]["statement"]["subject"] = [
                subject,
                {"digest": {"sha256": digest}},
            ]
            validate_attestation_receipt(
                document, predicate_type=predicate, artifact_hashes={digest}
            )
        with self.assertRaisesRegex(ValueError, "does not cover"):
            validate_attestation_receipt(
                receipt(), predicate_type=predicate, artifact_hashes={"b" * 64}
            )

    def test_writes_bound_machine_approval_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = self.artifacts(root)
            output = root / "APPROVAL.json"
            candidate = root / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "id": 123,
                        "conclusion": "success",
                        "name": "Release candidate",
                        "head_branch": "main",
                        "head_sha": "a" * 40,
                    }
                )
            )
            binding = root / "binding.json"
            binding.write_text(
                json.dumps(
                    {
                        "revision": "a" * 40,
                        "version": __version__,
                        "source_digest": "sha256:" + "b" * 64,
                    }
                )
            )

            def attestation(predicate_type):
                return [
                    {
                        "verificationResult": {
                            "statement": {
                                "predicateType": predicate_type,
                                "subject": [
                                    {
                                        "digest": {
                                            "sha256": hashlib.sha256(item.read_bytes()).hexdigest()
                                        }
                                    }
                                    for item in artifacts
                                ],
                            },
                            "verifiedTimestamps": [{}],
                            "signature": {"certificate": {}},
                        }
                    }
                ]

            provenance = root / "provenance.json"
            provenance.write_text(json.dumps(attestation("https://slsa.dev/provenance/v1")))
            sbom = root / "sbom.json"
            sbom.write_text(json.dumps(attestation("https://spdx.dev/Document/v2.3")))
            receipts = {
                "candidate-workflow-success": candidate,
                "main-branch-revision-bound": binding,
                "artifact-version-binding": binding,
                "artifact-build-provenance": provenance,
                "artifact-sbom-attestation": sbom,
            }
            write_approval_evidence(
                output,
                artifacts,
                version=__version__,
                revision="a" * 40,
                candidate_run_id="123",
                approval_run_id="456",
                repository="eii/repo",
                actor="reviewer",
                environment="production-release",
                run_url="https://example.test/runs/456",
                receipts=receipts,
            )
            document = json.loads(output.read_text())
            self.assertEqual(document["actor"], "reviewer")
            self.assertEqual(set(document["artifacts"]), {item.name for item in artifacts})
            self.assertEqual(
                set((root / "approval-receipts").iterdir()),
                {
                    root / "approval-receipts" / f"{name}.json"
                    for name, record in document["receipts"].items()
                },
            )
            with self.assertRaisesRegex(ValueError, "metadata"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="",
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            with self.assertRaisesRegex(ValueError, "unique"):
                write_approval_evidence(
                    output,
                    (artifacts[0], artifacts[0]),
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            with self.assertRaisesRegex(ValueError, "every verified check"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts={},
                )
            provenance.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "empty"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            provenance.write_text(json.dumps(attestation("https://slsa.dev/provenance/v1")))
            candidate.write_text("not-json")
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            candidate.write_text("{}")
            with self.assertRaisesRegex(ValueError, "requested run"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            candidate.write_text(
                json.dumps(
                    {
                        "id": 123,
                        "conclusion": "success",
                        "name": "Release candidate",
                        "head_branch": "main",
                        "head_sha": "a" * 40,
                    }
                )
            )
            binding.write_text("{}")
            with self.assertRaisesRegex(ValueError, "source binding"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )
            binding.write_text(
                json.dumps(
                    {
                        "revision": "a" * 40,
                        "version": __version__,
                        "source_digest": "sha256:" + "b" * 64,
                    }
                )
            )
            provenance.write_text("[]")
            with self.assertRaisesRegex(ValueError, "verified results"):
                write_approval_evidence(
                    output,
                    artifacts,
                    version=__version__,
                    revision="a" * 40,
                    candidate_run_id="123",
                    approval_run_id="456",
                    repository="eii/repo",
                    actor="reviewer",
                    environment="production-release",
                    run_url="https://example.test/runs/456",
                    receipts=receipts,
                )

    def test_source_tree_must_be_clean_and_match_revision(self):
        clean = subprocess.CompletedProcess([], 0, stdout="abc\n", stderr="")
        status = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("subprocess.run", side_effect=(clean, status)):
            self.assertEqual(require_clean_source_tree(Path("."), revision="abc"), "abc")
        dirty = subprocess.CompletedProcess([], 0, stdout=" M source.py\n", stderr="")
        with (
            patch("subprocess.run", side_effect=(clean, dirty)),
            self.assertRaisesRegex(ValueError, "dirty"),
        ):
            require_clean_source_tree(Path("."))
        with (
            patch("subprocess.run", side_effect=(clean, status)),
            self.assertRaisesRegex(ValueError, "does not match"),
        ):
            require_clean_source_tree(Path("."), revision="def")
        with (
            patch("subprocess.run", side_effect=OSError("git missing")),
            self.assertRaisesRegex(ValueError, "Git worktree"),
        ):
            require_clean_source_tree(Path("."))

    def artifacts(self, root: Path, version: str = __version__) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        metadata = f"Metadata-Version: 2.4\nName: eii-observatory\nVersion: {version}\n\n".encode()
        wheel = root / f"eii_observatory-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(f"eii_observatory-{version}.dist-info/METADATA", metadata)
        sdist = root / f"eii_observatory-{version}.tar.gz"
        with tarfile.open(sdist, "w:gz") as archive:
            member = tarfile.TarInfo(f"eii_observatory-{version}/PKG-INFO")
            member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
        return wheel, sdist

    def test_accepts_bound_wheel_sdist_and_optional_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel, sdist = self.artifacts(Path(directory))
            self.assertEqual(artifact_version(wheel), __version__)
            self.assertEqual(artifact_version(sdist), __version__)
            validate_release_candidate(
                (wheel, sdist), expected_version=__version__, tag=f"v{__version__}"
            )
            validate_release_candidate((wheel, sdist), expected_version=__version__)

    def test_rejects_version_tag_count_kind_and_artifact_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel, sdist = self.artifacts(root)
            with self.assertRaisesRegex(ValueError, "expected version"):
                validate_release_candidate((wheel, sdist), expected_version="9.9.9")
            with self.assertRaisesRegex(ValueError, "tag"):
                validate_release_candidate(
                    (wheel, sdist), expected_version=__version__, tag="v9.9.9"
                )
            with self.assertRaisesRegex(ValueError, "exactly one wheel"):
                validate_release_candidate((wheel,), expected_version=__version__)
            with self.assertRaisesRegex(ValueError, "exactly one wheel"):
                validate_release_candidate((wheel, wheel), expected_version=__version__)
            wrong = root / "wrong.whl"
            with zipfile.ZipFile(wrong, "w") as archive:
                archive.writestr("wrong.dist-info/METADATA", "Version: 9.9.9\n")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_release_candidate((wrong, sdist), expected_version=__version__)
            wrong_name = root / f"eii_observatory-{__version__}-bad.whl"
            with zipfile.ZipFile(wrong_name, "w") as archive:
                archive.writestr(
                    "wrong.dist-info/METADATA",
                    f"Name: another-project\nVersion: {__version__}\n",
                )
            with self.assertRaisesRegex(ValueError, "project name"):
                validate_release_candidate((wrong_name, sdist), expected_version=__version__)
            renamed_wheel = root / "renamed.whl"
            wheel.rename(renamed_wheel)
            with self.assertRaisesRegex(ValueError, "wheel filename"):
                validate_release_candidate((renamed_wheel, sdist), expected_version=__version__)
            wheel, renamed_sdist = self.artifacts(root / "renamed")
            bad_sdist_name = renamed_sdist.with_name("renamed.tar.gz")
            renamed_sdist.rename(bad_sdist_name)
            with self.assertRaisesRegex(ValueError, "sdist filename"):
                validate_release_candidate((wheel, bad_sdist_name), expected_version=__version__)

    def test_rejects_invalid_or_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "artifact.txt"
            text.write_text("not a package")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                artifact_version(text)
            wheel = root / "bad.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("one.dist-info/METADATA", "Version: 1\n")
                archive.writestr("two.dist-info/METADATA", "Version: 1\n")
            with self.assertRaisesRegex(ValueError, "exactly one METADATA"):
                artifact_version(wheel)
            wheel = root / "missing-version.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("one.dist-info/METADATA", "Name: p\n")
            with self.assertRaisesRegex(ValueError, "no Version"):
                artifact_version(wheel)
            with self.assertRaisesRegex(ValueError, "no Version"):
                validate_release_candidate(
                    (wheel, self.artifacts(root / "valid")[1]), expected_version=__version__
                )
            sdist = root / "bad.tar.gz"
            with tarfile.open(sdist, "w:gz") as archive:
                for name in ("one/PKG-INFO", "two/PKG-INFO"):
                    metadata = b"Version: 1\n"
                    member = tarfile.TarInfo(name)
                    member.size = len(metadata)
                    archive.addfile(member, io.BytesIO(metadata))
            with self.assertRaisesRegex(ValueError, "exactly one PKG-INFO"):
                artifact_version(sdist)
            with (
                patch("tarfile.TarFile.extractfile", return_value=None),
                self.assertRaisesRegex(ValueError, "unreadable"),
            ):
                artifact_version(self.artifacts(root / "nested")[1])


if __name__ == "__main__":
    unittest.main()
