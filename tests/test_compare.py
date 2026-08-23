import unittest

from eii.compare import compare_bundles


class ComparisonTests(unittest.TestCase):
    def test_reports_added_resolved_and_persistent_findings(self):
        def finding(kind, block):
            return {"finding_type": kind, "evidence": [{"block_id": block}], "severity": "high"}

        old = {"id": "old", "findings": [finding("missing", "a"), finding("dense", "b")]}
        new = {"id": "new", "findings": [finding("missing", "a"), finding("drift", "c")]}
        result = compare_bundles(old, new)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["resolved"]), 1)
        self.assertEqual(len(result["persistent"]), 1)
        self.assertTrue(result["regression"])


if __name__ == "__main__":
    unittest.main()
