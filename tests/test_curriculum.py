import tempfile
import unittest
from pathlib import Path

from eii.adapters import PlctExportAdapter
from eii.cli import main
from eii.curriculum import CurriculumMRI, CurriculumSpec

FIXTURES = Path(__file__).parent / "fixtures"


class CurriculumTests(unittest.TestCase):
    def test_reports_coverage_assessment_and_prerequisite_gaps(self):
        release = PlctExportAdapter().load(FIXTURES / "plct.json")
        spec = CurriculumSpec.load(FIXTURES / "curriculum.json")
        findings = CurriculumMRI().analyze(release, spec)
        kinds = {f.finding_type for f in findings}
        self.assertIn("curriculum.unassessed_objective", kinds)
        self.assertIn("curriculum.unsupported_objective", kinds)
        self.assertIn("curriculum.prerequisite_jump", kinds)
        self.assertIn("curriculum.unsupported_question", kinds)

    def test_mri_cli_writes_report_and_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mri"
            result = main(
                [
                    "mri",
                    str(FIXTURES / "plct.json"),
                    "--spec",
                    str(FIXTURES / "curriculum.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "backlog.json").exists())
            self.assertTrue((output / "regression-suite.json").exists())
            cases = __import__("json").loads((output / "regression-cases.json").read_text())[
                "cases"
            ]
            evidence = __import__("json").loads((output / "evidence.json").read_text())["findings"]
            self.assertEqual(len(cases), len(evidence))


if __name__ == "__main__":
    unittest.main()
