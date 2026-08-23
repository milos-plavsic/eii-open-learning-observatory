import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ModuleNotFoundError:
    Draft202012Validator = FormatChecker = None  # type: ignore[assignment,misc]

from eii import __version__
from eii.adapters import PlctExportAdapter
from eii.cli import main
from eii.domain import EvidenceBundle
from eii.evidence import write_bundle
from eii.plct_conformance import evaluate_plct_export, write_conformance_report
from eii.supply_chain import build_release_evidence
from eii.weather import WeatherStore

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def validator(name: str) -> Any:
    schema = json.loads((ROOT / "schemas" / name).read_text("utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@unittest.skipIf(Draft202012Validator is None, "install the test extra for schema conformance")
class SchemaConformanceTests(unittest.TestCase):
    def test_all_generated_artifacts_conform_and_negative_mutations_fail(self):
        plct = json.loads((FIXTURES / "plct.json").read_text("utf-8"))
        plct_validator = validator("plct-course-export-v1.schema.json")
        plct_validator.validate(plct)
        invalid_plct = copy.deepcopy(plct)
        invalid_plct["activities"][0]["activity_key"] = ""
        self.assertTrue(list(plct_validator.iter_errors(invalid_plct)))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = PlctExportAdapter().load(FIXTURES / "plct.json")
            evidence_path = root / "evidence.json"
            write_bundle(EvidenceBundle.create((release,), ()), evidence_path)
            evidence = json.loads(evidence_path.read_text("utf-8"))
            evidence_validator = validator("evidence-bundle.schema.json")
            evidence_validator.validate(evidence)
            invalid_evidence = copy.deepcopy(evidence)
            invalid_evidence["id"] = "not-a-hash"
            self.assertTrue(list(evidence_validator.iter_errors(invalid_evidence)))

            safety_path = root / "safety.json"
            self.assertEqual(
                main(
                    [
                        "safety-case",
                        str(FIXTURES / "plct.json"),
                        "--suite",
                        str(FIXTURES / "safety-suite.json"),
                        "--responses",
                        str(FIXTURES / "safety-responses.json"),
                        "--prompt-version",
                        "p1",
                        "--output",
                        str(safety_path),
                    ]
                ),
                0,
            )
            safety = json.loads(safety_path.read_text("utf-8"))
            safety_validator = validator("safety-case.schema.json")
            safety_validator.validate(safety)
            invalid_safety = copy.deepcopy(safety)
            invalid_safety["release_decision"] = "maybe"
            self.assertTrue(list(safety_validator.iter_errors(invalid_safety)))

            weather_path = root / "weather.json"
            with WeatherStore(
                root / "weather.db",
                secret=b"0123456789abcdef0123456789abcdef",
                minimum_group_size=2,
            ) as store:
                store.export(weather_path)
            weather = json.loads(weather_path.read_text("utf-8"))
            weather_validator = validator("weather-map.schema.json")
            weather_validator.validate(weather)
            invalid_weather = copy.deepcopy(weather)
            invalid_weather["privacy"]["raw_conversations_stored"] = True
            self.assertTrue(list(weather_validator.iter_errors(invalid_weather)))

            wheel = root / f"eii_observatory-{__version__}-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("eii/__init__.py", "")
            release_evidence = build_release_evidence(
                (wheel,),
                project="eii-observatory",
                version=__version__,
                revision="a" * 40,
                source_digest="sha256:" + "a" * 64,
                created_at="2026-08-23T00:00:00+00:00",
            )
            release_validator = validator("release-evidence-1.0.schema.json")
            release_validator.validate(release_evidence)
            invalid_release = copy.deepcopy(release_evidence)
            invalid_release["artifacts"][0]["sha256"] = "bad"
            self.assertTrue(list(release_validator.iter_errors(invalid_release)))

            manifest = {
                "schema_version": "2.0",
                "project": "eii-observatory",
                "version": __version__,
                "revision": "a" * 40,
                "files": {
                    name: {"sha256": "0" * 64, "size": 1}
                    for name in ("SHA256SUMS", "release-evidence.json", "sbom.spdx.json")
                },
            }
            manifest_validator = validator("release-manifest-2.0.schema.json")
            manifest_validator.validate(manifest)
            invalid_manifest = copy.deepcopy(manifest)
            invalid_manifest["files"].pop("SHA256SUMS")
            self.assertTrue(list(manifest_validator.iter_errors(invalid_manifest)))

            appliance_manifest = {
                "schema_version": "2.0",
                "package_id": "8a592bd1-4328-4ad8-8896-0873cf1b9737",
                "version": "1",
                "created_at": "2026-08-23T00:00:00+00:00",
                "files": {"content/course.json": "sha256:" + "a" * 64},
                "metadata": {},
            }
            appliance_validator = validator("appliance-package-manifest-2.0.schema.json")
            appliance_validator.validate(appliance_manifest)
            appliance_manifest["files"]["../escape"] = "sha256:" + "a" * 64
            self.assertTrue(list(appliance_validator.iter_errors(appliance_manifest)))

            conformance_path = root / "plct-conformance.json"
            write_conformance_report(evaluate_plct_export(FIXTURES / "plct.json"), conformance_path)
            conformance = json.loads(conformance_path.read_text("utf-8"))
            conformance_validator = validator("plct-conformance-report-v1.schema.json")
            conformance_validator.validate(conformance)
            invalid_conformance = copy.deepcopy(conformance)
            invalid_conformance["compatible"] = "yes"
            self.assertTrue(list(conformance_validator.iter_errors(invalid_conformance)))

            attestation = {
                "id": "sha256:" + "1" * 64,
                "key_fingerprint": "2" * 64,
                "signature": "ed25519:AA==",
                "statement": {
                    "schema_version": "1.0",
                    "organization": "Petlja",
                    "maintainer": "reviewer",
                    "repository_revision": "abc",
                    "reviewed_at": "2026-08-21T12:00:00+00:00",
                    "report_hash": "sha256:" + "3" * 64,
                    "export_hash": "sha256:" + "4" * 64,
                    "course_release_hash": "sha256:" + "5" * 64,
                },
            }
            attestation_validator = validator("plct-attestation-v1.schema.json")
            attestation_validator.validate(attestation)
            invalid_attestation = copy.deepcopy(attestation)
            invalid_attestation["key_fingerprint"] = "bad"
            self.assertTrue(list(attestation_validator.iter_errors(invalid_attestation)))

            external = {
                "id": "sha256:" + "1" * 64,
                "key_fingerprint": "2" * 64,
                "signature": "ed25519:AA==",
                "statement": {
                    "schema_version": "1.0",
                    "gate_type": "penetration-test",
                    "executed_at": "2026-08-21T12:00:00+00:00",
                    "organization": "lab",
                    "reviewer": "reviewer",
                    "scope": "release",
                    "procedure_version": "1",
                    "subject_hashes": ["sha256:" + "3" * 64],
                    "outcome": "passed",
                    "findings": [],
                    "limitations": [],
                },
            }
            external_validator = validator("external-validation-record-v1.schema.json")
            external_validator.validate(external)
            invalid_external = copy.deepcopy(external)
            invalid_external["statement"]["outcome"] = "maybe"
            self.assertTrue(list(external_validator.iter_errors(invalid_external)))


if __name__ == "__main__":
    unittest.main()
