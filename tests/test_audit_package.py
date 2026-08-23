import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, generate_keypair

from eii.alignment import relationship_id
from eii.audit_package import _signing_lock, _snapshot, sign_audit_directory, verify_signed_audit
from eii.cli import main
from eii.crypto import public_key_fingerprint, sign_ed25519
from eii.domain import EvidenceRef, ModelRun, canonical_json, to_dict
from eii.evidence import load_audit_directory, load_bundle, write_bundle
from eii.semantic_records import SemanticEvaluationRecord, model_run_id

FIXTURES = Path(__file__).parent / "fixtures"


class AuditPackageTests(unittest.TestCase):
    def _report(self, root):
        report = root / "report"
        main(
            [
                "audit",
                str(FIXTURES / "course_en"),
                str(FIXTURES / "course_sr"),
                "--output",
                str(report),
            ]
        )
        return report

    def test_authorization_policy_and_purpose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._report(root)
            created = "2026-08-24T10:00:00+00:00"
            sign_audit_directory(
                report,
                TEST_PRIVATE_KEY,
                TEST_PUBLIC_KEY,
                signer_id="eii-release",
                purpose="course-quality-audit",
                created_at=created,
            )
            fingerprint = public_key_fingerprint(TEST_PUBLIC_KEY)
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "trusted_signers": [
                            {
                                "signer_id": "eii-release",
                                "key_fingerprint": fingerprint,
                                "purposes": ["course-quality-audit"],
                                "valid_from": "2026-01-01T00:00:00+00:00",
                                "valid_until": "2027-01-01T00:00:00+00:00",
                            }
                        ],
                    }
                )
            )
            self.assertEqual(
                verify_signed_audit(
                    report,
                    TEST_PUBLIC_KEY,
                    authorization_policy=policy,
                    expected_purpose="course-quality-audit",
                    at_time=datetime(2026, 8, 24, 12, tzinfo=UTC),
                ),
                fingerprint,
            )
            with self.assertRaisesRegex(ValueError, "required purpose"):
                verify_signed_audit(report, TEST_PUBLIC_KEY, expected_purpose="procurement")
            with self.assertRaisesRegex(ValueError, "not authorized"):
                verify_signed_audit(
                    report,
                    TEST_PUBLIC_KEY,
                    authorization_policy=policy,
                    at_time=datetime(2028, 1, 1, tzinfo=UTC),
                )
            with self.assertRaisesRegex(ValueError, "verification time"):
                verify_signed_audit(
                    report,
                    TEST_PUBLIC_KEY,
                    authorization_policy=policy,
                    at_time=datetime(2026, 8, 24),
                )
            invalid_policies = (
                ({}, "policy is invalid"),
                ({"schema_version": "1.0", "trusted_signers": [{}]}, "signer entry"),
                (
                    {
                        "schema_version": "1.0",
                        "trusted_signers": [
                            {
                                "signer_id": "eii-release",
                                "key_fingerprint": fingerprint,
                                "purposes": ["course-quality-audit"],
                                "valid_from": "bad",
                                "valid_until": "2027-01-01T00:00:00+00:00",
                            }
                        ],
                    },
                    "validity interval",
                ),
                (
                    {
                        "schema_version": "1.0",
                        "trusted_signers": [
                            {
                                "signer_id": "eii-release",
                                "key_fingerprint": fingerprint,
                                "purposes": [7],
                                "valid_from": "2026-01-01T00:00:00+00:00",
                                "valid_until": "2027-01-01T00:00:00+00:00",
                            }
                        ],
                    },
                    "signer entry",
                ),
                (
                    {
                        "schema_version": "1.0",
                        "trusted_signers": [
                            {
                                "signer_id": "eii-release",
                                "key_fingerprint": fingerprint,
                                "purposes": ["course-quality-audit"],
                                "valid_from": "2027-01-01T00:00:00+00:00",
                                "valid_until": "2026-01-01T00:00:00+00:00",
                            }
                        ],
                    },
                    "validity interval",
                ),
            )
            for document, message in invalid_policies:
                policy.write_text(json.dumps(document))
                with self.assertRaisesRegex(ValueError, message):
                    verify_signed_audit(
                        report,
                        TEST_PUBLIC_KEY,
                        authorization_policy=policy,
                        at_time=datetime(2026, 8, 24, 12, tzinfo=UTC),
                    )

    def test_snapshot_and_signing_race_defenses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._report(root)
            (report / "index.html").unlink()
            with self.assertRaisesRegex(ValueError, "regular non-symbolic"):
                _snapshot(report)
            report = self._report(root)
            with patch("eii.audit_package.stat.S_ISREG", return_value=False):
                with self.assertRaisesRegex(ValueError, "signing lock"):
                    with _signing_lock(report):
                        pass
            with patch("eii.audit_package.MAX_AUDIT_FILE_BYTES", 0):
                with self.assertRaisesRegex(ValueError, "bounded package size"):
                    _snapshot(report)
            original_read = Path.read_bytes
            with patch.object(Path, "read_bytes", lambda path: original_read(path)[:-1]):
                with self.assertRaisesRegex(ValueError, "changed while it was read"):
                    _snapshot(report)
            files = _snapshot(report)
            changed = dict(files)
            changed["index.html"] += b" "
            with patch("eii.audit_package._snapshot", side_effect=[files, changed]):
                with self.assertRaisesRegex(ValueError, "changed while"):
                    sign_audit_directory(
                        report, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, signer_id="eii-release"
                    )
            for signer, purpose, timestamp, message in (
                ("", "audit", None, "identity"),
                ("signer", "", None, "identity"),
                ("signer", "audit", "2026-01-01T00:00:00", "timezone"),
                ("signer", "audit", "not-a-time", "time is invalid"),
            ):
                with self.assertRaisesRegex(ValueError, message):
                    sign_audit_directory(
                        report,
                        TEST_PRIVATE_KEY,
                        TEST_PUBLIC_KEY,
                        signer_id=signer,
                        purpose=purpose,
                        created_at=timestamp,
                    )
            with patch("eii.audit_package.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    sign_audit_directory(
                        report, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, signer_id="eii-release"
                    )

    def test_verification_rejects_invalid_signed_identity_time(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(Path(directory))
            sign_audit_directory(report, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, signer_id="eii-release")
            manifest_path = report / "AUDIT-MANIFEST.json"
            signature_path = report / "AUDIT-MANIFEST.ed25519.json"
            baseline = json.loads(manifest_path.read_text())
            malformed = dict(baseline)
            malformed.pop("purpose")
            manifest_path.write_text(json.dumps(malformed))
            with self.assertRaisesRegex(ValueError, "manifest is invalid"):
                verify_signed_audit(report, TEST_PUBLIC_KEY)
            for created_at, signer_id, purpose, message in (
                ("invalid", "eii-release", "course-quality-audit", "time is invalid"),
                (
                    "2026-01-01T00:00:00",
                    "eii-release",
                    "course-quality-audit",
                    "identity, purpose, and time",
                ),
                (
                    "2026-01-01T00:00:00+00:00",
                    "",
                    "course-quality-audit",
                    "identity, purpose, and time",
                ),
                (
                    "2026-01-01T00:00:00+00:00",
                    7,
                    "course-quality-audit",
                    "identity, purpose, and time",
                ),
                (
                    "2026-01-01T00:00:00+00:00",
                    "eii-release",
                    7,
                    "identity, purpose, and time",
                ),
            ):
                manifest = dict(baseline)
                manifest["created_at"], manifest["signer_id"], manifest["purpose"] = (
                    created_at,
                    signer_id,
                    purpose,
                )
                manifest_path.write_text(json.dumps(manifest))
                signature_path.write_text(
                    json.dumps(
                        {
                            "algorithm": "Ed25519",
                            "signature": sign_ed25519(
                                canonical_json(manifest).encode(), TEST_PRIVATE_KEY
                            ),
                        }
                    )
                )
                with self.assertRaisesRegex(ValueError, message):
                    verify_signed_audit(report, TEST_PUBLIC_KEY)

            sign_audit_directory(
                report,
                TEST_PRIVATE_KEY,
                TEST_PUBLIC_KEY,
                signer_id="eii-release",
                created_at="2027-01-01T00:00:00+00:00",
            )
            with self.assertRaisesRegex(ValueError, "future"):
                verify_signed_audit(
                    report,
                    TEST_PUBLIC_KEY,
                    at_time=datetime(2026, 1, 1, tzinfo=UTC),
                )

    def test_directory_validation_requires_well_formed_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(Path(directory))
            bundle = load_bundle(report / "evidence.json")
            for artifacts, message in ((None, "no audit artifact"), ({}, "invalid alignments")):
                metadata = {
                    key: value
                    for key, value in bundle.metadata.items()
                    if key not in {"semantic_evaluations", "semantic_evaluations_schema_version"}
                    and key != "semantic_evaluation_plan"
                }
                if artifacts is None:
                    metadata.pop("audit_artifacts")
                else:
                    metadata["audit_artifacts"] = artifacts
                write_bundle(replace(bundle, metadata=metadata, id=""), report / "evidence.json")
                with self.assertRaisesRegex(ValueError, message):
                    load_audit_directory(report)

    def test_rejects_unversioned_and_dangling_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report"
            main(
                [
                    "audit",
                    str(FIXTURES / "course_en"),
                    str(FIXTURES / "course_sr"),
                    "--output",
                    str(report),
                ]
            )
            bundle = load_bundle(report / "evidence.json")
            original_bundle = bundle
            metadata = dict(bundle.metadata)
            metadata.pop("semantic_evaluations_schema_version")
            write_bundle(replace(bundle, metadata=metadata, id=""), report / "evidence.json")
            with self.assertRaisesRegex(ValueError, "no supported semantic"):
                load_audit_directory(report)

            bundle = original_bundle
            run = ModelRun("p", "m", "v", {}, "input", "output")
            block = bundle.course_releases[0].blocks[0]
            reference = EvidenceRef(bundle.course_releases[0].id, block.id, block.hash, block.text)
            alignment = bundle.metadata["audit_artifacts"]["alignments"]["records"][0]
            relationship = relationship_id(
                alignment["concept_id"], tuple(tuple(member) for member in alignment["members"])
            )
            record = SemanticEvaluationRecord(
                "",
                relationship,
                (reference,),
                (reference,),
                "equivalent",
                1,
                {"same": True},
                "same",
                model_run_id(run),
            )
            metadata = dict(bundle.metadata)
            metadata["semantic_evaluations_schema_version"] = "1.0"
            metadata["semantic_evaluations"] = [to_dict(record)]
            write_bundle(replace(bundle, metadata=metadata, id=""), report / "evidence.json")
            with self.assertRaisesRegex(ValueError, "unknown model run"):
                load_audit_directory(report)

            bad_reference = replace(reference, block_hash="sha256:" + "0" * 64)
            right_member = alignment["members"][1]
            right_release = next(
                release for release in bundle.course_releases if release.id == right_member[0]
            )
            right_block = next(
                block for block in right_release.blocks if block.id == right_member[1]
            )
            right_reference = EvidenceRef(
                right_release.id,
                right_block.id,
                right_block.hash,
                right_block.text[:240] or None,
            )
            bad_record = SemanticEvaluationRecord(
                "",
                relationship,
                (reference,),
                (replace(right_reference, block_hash=bad_reference.block_hash),),
                "equivalent",
                1,
                {"same": True},
                "same",
                model_run_id(run),
            )
            metadata["semantic_evaluations"] = [to_dict(bad_record)]
            write_bundle(
                replace(bundle, metadata=metadata, model_runs=(run,), id=""),
                report / "evidence.json",
            )
            with self.assertRaisesRegex(ValueError, "invalid evidence reference"):
                load_audit_directory(report)

            metadata["semantic_evaluations"] = [to_dict(record), to_dict(record)]
            write_bundle(
                replace(bundle, metadata=metadata, model_runs=(run,), id=""),
                report / "evidence.json",
            )
            with self.assertRaisesRegex(ValueError, "identifiers must be unique"):
                load_audit_directory(report)

    def test_bundle_semantic_graph_rejects_cross_component_contradictions(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(Path(directory))
            bundle = load_bundle(report / "evidence.json")
            alignment = bundle.metadata["audit_artifacts"]["alignments"]["records"][0]
            blocks = {
                (release.id, block.id): block
                for release in bundle.course_releases
                for block in release.blocks
            }
            left_member, right_member = alignment["members"][:2]
            left_block, right_block = blocks[tuple(left_member)], blocks[tuple(right_member)]
            left = EvidenceRef(
                left_member[0], left_member[1], left_block.hash, left_block.text[:240] or None
            )
            right = EvidenceRef(
                right_member[0], right_member[1], right_block.hash, right_block.text[:240] or None
            )
            run = ModelRun("p", "m", "v", {}, "input", "output")
            record = SemanticEvaluationRecord(
                "",
                relationship_id(
                    alignment["concept_id"], tuple(tuple(member) for member in alignment["members"])
                ),
                (left,),
                (right,),
                "equivalent",
                1,
                {"same": True},
                "same",
                model_run_id(run),
            )
            metadata = dict(bundle.metadata)
            metadata["semantic_evaluations"] = [to_dict(record)]
            metadata["semantic_evaluation_plan"] = [
                {
                    "relationship_id": record.relationship_id,
                    "left_release_id": left.course_release_id,
                    "right_release_id": right.course_release_id,
                }
            ]
            valid = replace(bundle, metadata=metadata, model_runs=(run,), id="")
            path = Path(directory) / "semantic.json"
            write_bundle(valid, path)
            self.assertEqual(load_bundle(path).model_runs, (run,))

            def rejects_metadata(changes, message):
                changed_metadata = dict(metadata)
                changed_metadata.update(changes)
                write_bundle(replace(valid, metadata=changed_metadata, id=""), path)
                with self.assertRaisesRegex(ValueError, message):
                    load_bundle(path)

            plan = metadata["semantic_evaluation_plan"]
            rejects_metadata({"semantic_evaluation_plan": None}, "sealed evaluation plan")
            rejects_metadata({"semantic_evaluation_plan": [{}]}, "plan item is invalid")
            rejects_metadata({"semantic_evaluation_plan": [*plan, *plan]}, "inconsistent")
            rejects_metadata(
                {"semantic_evaluation_plan": [{**plan[0], "right_release_id": "unknown-release"}]},
                "inconsistent",
            )
            rejects_metadata({"semantic_evaluations": []}, "exactly satisfy")
            rejects_metadata(
                {
                    "semantic_evaluations": [
                        to_dict(replace(record, id="", left_evidence=(left, right)))
                    ]
                },
                "two distinct releases",
            )
            duplicate_result = replace(record, id="", explanation="same again")
            rejects_metadata(
                {"semantic_evaluations": [to_dict(record), to_dict(duplicate_result)]},
                "multiple results",
            )
            rejects_metadata(
                {"semantic_evaluations": [to_dict(replace(record, id="", properties={}))]},
                "require property",
            )
            rejects_metadata(
                {
                    "semantic_evaluations": [
                        to_dict(replace(record, id="", properties={"same": False}))
                    ]
                },
                "all properties",
            )
            rejects_metadata(
                {"semantic_evaluations": [to_dict(replace(record, id="", outcome="drift"))]},
                "at least one failed",
            )

            artifacts_with_duplicate = dict(metadata["audit_artifacts"])
            alignment_copy = dict(artifacts_with_duplicate["alignments"])
            alignment_copy["records"] = [*alignment_copy["records"], alignment_copy["records"][0]]
            artifacts_with_duplicate["alignments"] = alignment_copy
            rejects_metadata(
                {"audit_artifacts": artifacts_with_duplicate},
                "relationship identifiers must be unique",
            )

            finding = replace(bundle.findings[0], model_run=run)
            write_bundle(
                replace(bundle, findings=(finding,), model_runs=(), metadata={}, id=""), path
            )
            with self.assertRaisesRegex(ValueError, "absent from the bundle"):
                load_bundle(path)

            cases = []
            cases.append((replace(record, id="", relationship_id="unknown"), "unknown alignment"))
            cases.append(
                (
                    replace(record, id="", left_evidence=(replace(left, excerpt="false"),)),
                    "non-canonical",
                )
            )
            other = next(
                member
                for item in bundle.metadata["audit_artifacts"]["alignments"]["records"][1:]
                for member in item["members"]
            )
            other_block = blocks[tuple(other)]
            outside = EvidenceRef(
                other[0], other[1], other_block.hash, other_block.text[:240] or None
            )
            cases.append(
                (replace(record, id="", left_evidence=(outside,)), "outside its alignment")
            )
            cases.append(
                (
                    replace(
                        record,
                        id="",
                        member_judgments=({"member_index": 0, "error_type": "timeout"},),
                    ),
                    "member judgments",
                )
            )
            cases.append(
                (
                    replace(record, id="", outcome="drift", properties={"same": False}),
                    "finding projection",
                )
            )
            for changed, message in cases:
                changed_metadata = dict(metadata)
                changed_metadata["semantic_evaluations"] = [to_dict(changed)]
                write_bundle(replace(valid, metadata=changed_metadata, id=""), path)
                with self.assertRaisesRegex(ValueError, message):
                    load_bundle(path)

            changed_metadata = dict(metadata)
            artifacts = dict(changed_metadata["audit_artifacts"])
            alignment_artifact = dict(artifacts["alignments"])
            alignment_artifact["records"] = [{"concept_id": "x", "members": "bad"}]
            artifacts["alignments"] = alignment_artifact
            changed_metadata["audit_artifacts"] = artifacts
            write_bundle(replace(valid, metadata=changed_metadata, id=""), path)
            with self.assertRaisesRegex(ValueError, "alignment record is invalid"):
                load_bundle(path)

            malformed_alignment = dict(alignment)
            malformed_alignment["members"] = [
                ["only-one-field"],
                alignment["members"][1],
            ]
            alignment_artifact["records"] = [malformed_alignment]
            artifacts["alignments"] = alignment_artifact
            changed_metadata["audit_artifacts"] = artifacts
            write_bundle(replace(valid, metadata=changed_metadata, id=""), path)
            with self.assertRaisesRegex(ValueError, "alignment member is invalid"):
                load_bundle(path)

    def test_sign_verify_wrong_key_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report"
            self.assertEqual(
                main(
                    [
                        "audit",
                        str(FIXTURES / "course_en"),
                        str(FIXTURES / "course_sr"),
                        "--output",
                        str(report),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "audit-sign",
                        str(report),
                        "--private-key-file",
                        str(TEST_PRIVATE_KEY),
                        "--public-key-file",
                        str(TEST_PUBLIC_KEY),
                        "--signer-id",
                        "eii-release",
                    ]
                ),
                0,
            )
            signature = report / "AUDIT-MANIFEST.ed25519.json"
            self.assertTrue(signature.is_file())
            self.assertTrue(verify_signed_audit(report, TEST_PUBLIC_KEY))
            self.assertEqual(
                main(["audit-verify", str(report), "--public-key-file", str(TEST_PUBLIC_KEY)]), 0
            )
            _, wrong_public = generate_keypair(root, "wrong")
            with self.assertRaisesRegex(ValueError, "authentication"):
                verify_signed_audit(report, wrong_public)
            manifest = report / "AUDIT-MANIFEST.json"
            document = json.loads(manifest.read_text())
            document["bundle_id"] = "sha256:" + "0" * 64
            manifest.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "authentication"):
                verify_signed_audit(report, TEST_PUBLIC_KEY)
            (report / "AUDIT-MANIFEST.ed25519.json").write_text(
                json.dumps(
                    {
                        "algorithm": "Ed25519",
                        "signature": sign_ed25519(
                            canonical_json(document).encode(), TEST_PRIVATE_KEY
                        ),
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "bundle identity"):
                verify_signed_audit(report, TEST_PUBLIC_KEY)

    def test_rejects_mismatched_signing_keys_and_authenticated_file_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report"
            main(
                [
                    "audit",
                    str(FIXTURES / "course_en"),
                    str(FIXTURES / "course_sr"),
                    "--output",
                    str(report),
                ]
            )
            wrong_private, _ = generate_keypair(root, "wrong")
            with self.assertRaisesRegex(ValueError, "do not match"):
                sign_audit_directory(
                    report, wrong_private, TEST_PUBLIC_KEY, signer_id="eii-release"
                )
            sign_audit_directory(report, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, signer_id="eii-release")
            manifest_path = report / "AUDIT-MANIFEST.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"]["index.html"]["size"] += 1
            manifest_path.write_text(json.dumps(manifest))
            signature_path = report / "AUDIT-MANIFEST.ed25519.json"
            signature_path.write_text(
                json.dumps(
                    {
                        "algorithm": "Ed25519",
                        "signature": sign_ed25519(
                            canonical_json(manifest).encode(), TEST_PRIVATE_KEY
                        ),
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "file mismatch"):
                verify_signed_audit(report, TEST_PUBLIC_KEY)


if __name__ == "__main__":
    unittest.main()
