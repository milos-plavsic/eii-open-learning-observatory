import json
import tempfile
import unittest
from pathlib import Path

from eii.cli import main

DEMO = Path(__file__).parents[1] / "examples" / "cocreate-mini"


class SixLanguageDemoTests(unittest.TestCase):
    def test_end_to_end_report_has_six_releases_and_known_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report"
            sources = [str(DEMO / language) for language in ("en", "sr", "es", "pt", "ca", "hr")]
            result = main(
                [
                    "audit",
                    *sources,
                    "--glossary",
                    str(DEMO / "glossary.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(result, 0)
            evidence = json.loads((output / "evidence.json").read_text())
            self.assertEqual(len(evidence["course_releases"]), 6)
            self.assertIn(
                "translation.missing_unit", {item["finding_type"] for item in evidence["findings"]}
            )
            self.assertNotIn(
                "translation.number_or_unit_drift",
                {item["finding_type"] for item in evidence["findings"]},
            )
            status = json.loads((output / "translation-status.json").read_text())
            self.assertIn("missing-translation", {item["state"] for item in status})
            suite = json.loads((DEMO / "cross-language-safety-suite.json").read_text())
            self.assertEqual(len(suite["fixtures"]), 5)


if __name__ == "__main__":
    unittest.main()
