import json
import tempfile
import unittest
from pathlib import Path

from eii.cli import main

ROOT = Path(__file__).parents[1]
CORPUS = Path(__file__).parent / "accuracy_corpus" / "corpus.json"
SEVERITY_RANK = {"none": -1, "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def assert_severity_ceiling(test: unittest.TestCase, findings: list[dict], ceiling: str) -> None:
    """Assert a labeled corpus ceiling without silently accepting an unknown label."""
    if ceiling not in SEVERITY_RANK:
        raise ValueError(f"unknown accuracy-corpus severity: {ceiling}")
    actual = max((SEVERITY_RANK[item["severity"]] for item in findings), default=-1)
    test.assertLessEqual(actual, SEVERITY_RANK[ceiling])


class GoldenAccuracyCorpusTests(unittest.TestCase):
    def test_labeled_multilingual_outputs(self):
        document = json.loads(CORPUS.read_text("utf-8"))
        self.assertEqual(document["schema_version"], "1.0")
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
                actual = {item["finding_type"] for item in evidence["findings"]}
                self.assertLessEqual(set(case["expected"]), actual)
                self.assertTrue(actual.isdisjoint(case["forbidden"]))
                if ceiling := case.get("maximum_finding_severity"):
                    assert_severity_ceiling(self, evidence["findings"], ceiling)

    def test_unknown_severity_ceiling_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown accuracy-corpus severity"):
            assert_severity_ceiling(self, [], "urgent")


if __name__ == "__main__":
    unittest.main()
