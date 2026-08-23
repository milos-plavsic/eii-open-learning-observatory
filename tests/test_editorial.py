import json
import tempfile
import unittest
from pathlib import Path

from eii.adapters import PlctExportAdapter
from eii.domain import EvidenceBundle
from eii.editorial import LLMEditorialAuditor
from eii.evidence import write_bundle
from eii.fixture_export import (
    export_finding_regressions,
    export_findings_as_suite,
    verify_finding_regressions,
)
from eii.models import OpenAICompatibleClient

FIXTURES = Path(__file__).parent / "fixtures"


class EditorialTests(unittest.TestCase):
    def test_editorial_findings_require_valid_citations(self):
        response = {
            "findings": [
                {
                    "kind": "weak_example",
                    "title": "Only one example",
                    "explanation": "The bound is not varied.",
                    "severity": "medium",
                    "confidence": 0.8,
                    "block_ids": ["plct:loops:a1"],
                    "suggested_action": "Add a counterexample.",
                }
            ]
        }
        client = OpenAICompatibleClient(
            "http://localhost/v1",
            "editor",
            transport=lambda *args: {"choices": [{"message": {"content": json.dumps(response)}}]},
        )
        release = PlctExportAdapter().load(FIXTURES / "plct.json")
        findings = LLMEditorialAuditor(client).analyze(release)
        self.assertEqual(findings[0].finding_type, "curriculum.weak_example")
        self.assertEqual(findings[0].evidence[0].block_id, "plct:loops:a1")

    def test_unretrievable_questions_export_as_safety_fixtures(self):
        response = {
            "questions": [
                {
                    "id": "q1",
                    "question": "What is a banana invariant?",
                    "expected_block_ids": ["plct:loops:a1"],
                }
            ]
        }
        client = OpenAICompatibleClient(
            "http://localhost/v1",
            "generator",
            transport=lambda *args: {"choices": [{"message": {"content": json.dumps(response)}}]},
        )
        release = PlctExportAdapter().load(FIXTURES / "plct.json")
        findings = LLMEditorialAuditor(client).generate_support_tests(release)
        self.assertEqual(len(findings), 1)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "suite.json"
            export_findings_as_suite(findings, destination, version="course-2")
            suite = json.loads(destination.read_text())
            self.assertEqual(
                suite["fixtures"][0]["properties"]["expected_citation_ids"], ["plct:loops:a1"]
            )
            cases = Path(directory) / "cases.json"
            evidence = Path(directory) / "evidence.json"
            export_finding_regressions(findings, cases, version="course-2")
            write_bundle(EvidenceBundle.create((release,), findings), evidence)
            result = verify_finding_regressions(cases, evidence)
            self.assertEqual(result["still_present"], 1)


if __name__ == "__main__":
    unittest.main()
