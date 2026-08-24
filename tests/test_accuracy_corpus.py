import json
import tempfile
import unittest
from pathlib import Path

from eii.cli import main

ROOT = Path(__file__).parents[1]
CORPUS = Path(__file__).parent / "accuracy_corpus" / "corpus.json"
CASE_FIELDS = {"id", "sources", "glossary", "expected_findings", "provenance"}
FINDING_FIELDS = {"finding_type", "severity", "affected_languages", "evidence"}
EVIDENCE_FIELDS = {"language", "locator", "excerpt"}


def finding_projection(item: dict, release_languages: dict[str, str]) -> dict:
    """Project generated evidence onto every human-labeled correctness field."""
    return {
        "finding_type": item["finding_type"],
        "severity": item["severity"],
        "affected_languages": item["affected_languages"],
        "evidence": [
            {
                "language": release_languages[reference["course_release_id"]],
                "locator": reference["block_id"].removeprefix("repo:"),
                "excerpt": reference["excerpt"],
            }
            for reference in item["evidence"]
        ],
    }


class GoldenAccuracyCorpusTests(unittest.TestCase):
    def test_corpus_has_a_non_shrinking_validation_floor(self):
        document = json.loads(CORPUS.read_text("utf-8"))
        cases = document["cases"]
        identifiers = [case["id"] for case in cases]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertGreaterEqual(len(cases), 4)
        self.assertGreaterEqual(sum(not case["expected_findings"] for case in cases), 2)
        self.assertTrue(any(case["expected_findings"] for case in cases))
        self.assertTrue(all(case.get("provenance") for case in cases))
        for case in cases:
            self.assertLessEqual(set(case), CASE_FIELDS)
            self.assertEqual(set(case) - {"glossary"}, CASE_FIELDS - {"glossary"})
            for finding in case["expected_findings"]:
                self.assertEqual(set(finding), FINDING_FIELDS)
                self.assertTrue(finding["affected_languages"])
                self.assertTrue(finding["evidence"])
                self.assertTrue(
                    all(set(reference) == EVIDENCE_FIELDS for reference in finding["evidence"])
                )
        languages = {Path(source).name for case in cases for source in case["sources"]}
        self.assertTrue({"en", "sr", "es", "pt", "ca", "hr"}.issubset(languages))

    def test_labeled_multilingual_outputs(self):
        document = json.loads(CORPUS.read_text("utf-8"))
        self.assertEqual(document["schema_version"], "2.0")
        self.assertTrue(document["cases"])
        for case in document["cases"]:
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                arguments = [
                    "audit",
                    *(str(ROOT / source) for source in case["sources"]),
                    "--output",
                    directory,
                ]
                if glossary := case.get("glossary"):
                    arguments.extend(("--glossary", str(ROOT / glossary)))
                self.assertEqual(main(arguments), 0)
                evidence = json.loads((Path(directory) / "evidence.json").read_text("utf-8"))
                release_languages = {
                    release["id"]: release["language"] for release in evidence["course_releases"]
                }
                actual = sorted(
                    (finding_projection(item, release_languages) for item in evidence["findings"]),
                    key=lambda item: item["finding_type"],
                )
                expected = sorted(case["expected_findings"], key=lambda item: item["finding_type"])
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
