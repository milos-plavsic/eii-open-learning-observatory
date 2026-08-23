import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from eii.supply_chain import (
    artifact_kind,
    build_release_evidence,
    normalize_sdist_gzip,
    runtime_components,
    sha256_file,
    sign_release_evidence,
    verify_release_evidence,
    verify_signed_release,
    verify_spdx_document,
    write_release_evidence,
)


class SupplyChainTests(unittest.TestCase):
    def test_rejects_invalid_source_digest(self):
        with self.assertRaisesRegex(ValueError, "source digest"):
            build_release_evidence((), project="p", version="1", revision="r", source_digest="bad")

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_signed_release_evidence_and_all_trust_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "p.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("p/x", "x")
            evidence = root / "evidence"
            write_release_evidence(
                build_release_evidence(
                    (wheel,),
                    project="p",
                    version="1",
                    revision="r",
                    source_digest="sha256:" + "a" * 64,
                ),
                evidence,
            )
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True
            )
            signature_path = sign_release_evidence(evidence, private, public)
            verify_signed_release(evidence, root, public)
            evidence_path = evidence / "release-evidence.json"
            original_evidence = evidence_path.read_text()
            tampered_evidence = json.loads(original_evidence)
            tampered_evidence["revision"] = "attacker"
            evidence_path.write_text(json.dumps(tampered_evidence))
            with self.assertRaisesRegex(ValueError, "evidence mismatch"):
                verify_signed_release(evidence, root, public)
            evidence_path.write_text(original_evidence)
            sbom_path = evidence / "sbom.spdx.json"
            original_sbom = sbom_path.read_text()
            sbom_path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "evidence mismatch"):
                verify_signed_release(evidence, root, public)
            sbom_path.write_text(original_sbom)
            with (
                patch("eii.supply_chain.verify_ed25519", return_value=False),
                self.assertRaisesRegex(ValueError, "do not match"),
            ):
                sign_release_evidence(evidence, private, public)
            missing = root / "missing"
            missing.mkdir()
            with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
                sign_release_evidence(missing, private, public)
            original = signature_path.read_text()
            document = json.loads(original)
            document["algorithm"] = "wrong"
            signature_path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "document is invalid"):
                verify_signed_release(evidence, root, public)
            document = json.loads(original)
            document["key_fingerprint"] = "bad"
            signature_path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                verify_signed_release(evidence, root, public)
            document = json.loads(original)
            document["signature"] = "bad"
            signature_path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "signature verification"):
                verify_signed_release(evidence, root, public)
            signature_path.write_text(original)
            manifest_path = evidence / "RELEASE-MANIFEST.json"
            original_manifest = manifest_path.read_text()
            manifest = json.loads(original_manifest)
            manifest["schema_version"] = "wrong"
            manifest_path.write_text(json.dumps(manifest))
            with (
                patch("eii.supply_chain.verify_ed25519", return_value=True),
                self.assertRaisesRegex(ValueError, "manifest is invalid"),
            ):
                verify_signed_release(evidence, root, public)
            manifest = json.loads(original_manifest)
            manifest["files"].pop("sbom.spdx.json")
            manifest_path.write_text(json.dumps(manifest))
            with (
                patch("eii.supply_chain.verify_ed25519", return_value=True),
                self.assertRaisesRegex(ValueError, "file set"),
            ):
                verify_signed_release(evidence, root, public)
            manifest = json.loads(original_manifest)
            manifest["revision"] = "wrong"
            manifest_path.write_text(json.dumps(manifest))
            with (
                patch("eii.supply_chain.verify_ed25519", return_value=True),
                self.assertRaisesRegex(ValueError, "identity"),
            ):
                verify_signed_release(evidence, root, public)
            manifest = json.loads(original_manifest)
            sbom_path = evidence / "sbom.spdx.json"
            sbom_path.write_text("{}")
            manifest["files"]["sbom.spdx.json"] = {
                "sha256": sha256_file(sbom_path),
                "size": sbom_path.stat().st_size,
            }
            manifest_path.write_text(json.dumps(manifest))
            with (
                patch("eii.supply_chain.verify_ed25519", return_value=True),
                self.assertRaisesRegex(ValueError, "SBOM"),
            ):
                verify_signed_release(evidence, root, public)

    def test_generate_write_and_verify_release_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "p-1-py3-none-any.whl"
            sdist = root / "p-1.tar.gz"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("p/x", "x")
            source = root / "x"
            source.write_text("x")
            with tarfile.open(sdist, "w:gz") as archive:
                archive.add(source, arcname="p-1/x")
            normalize_sdist_gzip(sdist)
            evidence = build_release_evidence(
                (sdist, wheel),
                project="p",
                version="1",
                revision="abc",
                source_digest="sha256:" + "a" * 64,
                created_at="2026-01-01T00:00:00+00:00",
            )
            output = root / "evidence"
            write_release_evidence(evidence, output)
            verify_release_evidence(output / "release-evidence.json", root)
            original_wheel = wheel.read_bytes()
            self.assertEqual(artifact_kind(wheel), "python-wheel")
            self.assertEqual(len(sha256_file(wheel)), 64)
            self.assertIn("p-1", (output / "SHA256SUMS").read_text())
            evidence_path = output / "release-evidence.json"
            document = json.loads(evidence_path.read_text())
            package_names = {item["name"] for item in document["spdx"]["packages"]}
            self.assertEqual(package_names, {"p", "defusedxml", "rfc8785"})
            self.assertEqual(
                sum(
                    relationship["relationshipType"] == "DEPENDS_ON"
                    for relationship in document["spdx"]["relationships"]
                ),
                2,
            )
            original = evidence_path.read_text()
            document["artifacts"][0]["name"] = "../escape.whl"
            evidence_path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "basename"):
                verify_release_evidence(evidence_path, root)
            document = json.loads(original)
            document["artifacts"][0]["kind"] = "wrong"
            evidence_path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "missing or invalid"):
                verify_release_evidence(evidence_path, root)
            evidence_path.write_text(original)
            wheel.write_bytes(original_wheel + b"x")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_release_evidence(evidence_path, root)
            wheel.write_bytes(
                original_wheel[:10] + bytes([original_wheel[10] ^ 1]) + original_wheel[11:]
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_release_evidence(evidence_path, root)

    def test_rejects_empty_duplicate_unsupported_and_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "x.txt"
            bad.write_text("x")
            with self.assertRaises(ValueError):
                artifact_kind(bad)
            with self.assertRaises(ValueError):
                normalize_sdist_gzip(bad)
            with self.assertRaisesRegex(ValueError, "at least one"):
                build_release_evidence(
                    (), project="p", version="1", revision="r", source_digest="sha256:" + "a" * 64
                )
            a = root / "a" / "same.whl"
            b = root / "b" / "same.whl"
            for path in (a, b):
                path.parent.mkdir()
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("x", "x")
            with self.assertRaisesRegex(ValueError, "unique"):
                build_release_evidence(
                    (a, b),
                    project="p",
                    version="1",
                    revision="r",
                    source_digest="sha256:" + "a" * 64,
                )
            with self.assertRaisesRegex(ValueError, "timezone"):
                build_release_evidence(
                    (a,),
                    project="p",
                    version="1",
                    revision="r",
                    source_digest="sha256:" + "a" * 64,
                    created_at="2026-01-01T00:00:00",
                )
            evidence = root / "e.json"
            evidence.write_text('{"artifacts":[]}')
            with self.assertRaisesRegex(ValueError, "no artifacts"):
                verify_release_evidence(evidence, root)
            with self.assertRaisesRegex(ValueError, "must be a list"):
                write_release_evidence({"artifacts": {}, "spdx": {}}, root / "out")

            invalid_project = root / "pyproject.toml"
            invalid_project.write_text('[project]\ndependencies=["unknown>=1"]\n')
            with self.assertRaisesRegex(ValueError, "exactly pinned"):
                runtime_components(invalid_project)
            invalid_project.write_text('[project]\ndependencies=["unknown==1"]\n')
            with self.assertRaisesRegex(ValueError, "SPDX metadata"):
                runtime_components(invalid_project)
            self.assertEqual(len(runtime_components(root / "absent.toml")), 2)

            with self.assertRaisesRegex(ValueError, "SPDX 2.3"):
                verify_spdx_document({})
            with self.assertRaisesRegex(ValueError, "arrays"):
                verify_spdx_document({"spdxVersion": "SPDX-2.3"})
            valid_spdx = build_release_evidence(
                (a,), project="p", version="1", revision="r", source_digest="sha256:" + "a" * 64
            )["spdx"]
            duplicate = json.loads(json.dumps(valid_spdx))
            duplicate["packages"].append(duplicate["packages"][0])
            with self.assertRaisesRegex(ValueError, "identities"):
                verify_spdx_document(duplicate)
            invalid_relationship = json.loads(json.dumps(valid_spdx))
            invalid_relationship["relationships"][0]["relatedSpdxElement"] = "missing"
            with self.assertRaisesRegex(ValueError, "relationship"):
                verify_spdx_document(invalid_relationship)
            dependency_drift = json.loads(json.dumps(valid_spdx))
            dependency_drift["relationships"] = dependency_drift["relationships"][:1]
            with self.assertRaisesRegex(ValueError, "dependency graph"):
                verify_spdx_document(dependency_drift)

            malformed = build_release_evidence(
                (a,), project="p", version="1", revision="r", source_digest="sha256:" + "a" * 64
            )
            malformed["artifacts"][0]["extra"] = True
            malformed_path = root / "malformed.json"
            malformed_path.write_text(json.dumps(malformed))
            with self.assertRaisesRegex(ValueError, "record is invalid"):
                verify_release_evidence(malformed_path, a.parent)


if __name__ == "__main__":
    unittest.main()
