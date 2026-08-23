import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from eii.cli import main
from eii.domain import FindingStatus, ReviewDecision
from eii.reviews import append_review, read_reviews


class ReviewTests(unittest.TestCase):
    def test_decisions_are_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.jsonl"
            decision = ReviewDecision(
                "f1", FindingStatus.CONFIRMED, "editor-1", "Verified", datetime.now(UTC).isoformat()
            )
            append_review(path, decision)
            append_review(
                path,
                ReviewDecision(
                    "f1",
                    FindingStatus.RESOLVED,
                    "editor-2",
                    "Patched",
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.assertEqual(
                [r.decision for r in read_reviews(path)],
                [FindingStatus.CONFIRMED, FindingStatus.RESOLVED],
            )

    def test_cli_records_intentional_localization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.jsonl"
            result = main(
                [
                    "review",
                    "babel:f1",
                    "intentional_localization",
                    "--reviewer",
                    "editor",
                    "--rationale",
                    "Localized example is intentional",
                    "--reviews",
                    str(path),
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual(read_reviews(path)[0].decision, FindingStatus.INTENTIONAL_LOCALIZATION)

    def test_cli_records_protocol_fields_and_abstention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.jsonl"
            result = main(
                [
                    "review",
                    "babel:f2",
                    "cannot_determine",
                    "--reviewer",
                    "reviewer-7",
                    "--rationale",
                    "Source version is ambiguous",
                    "--reviews",
                    str(path),
                    "--evidence-quality",
                    "incomplete",
                    "--severity-assessment",
                    "medium",
                    "--usefulness",
                    "2",
                    "--actionability",
                    "needs_revision",
                    "--seconds-spent",
                    "83",
                    "--review-round",
                    "blinded-findings",
                ]
            )
            self.assertEqual(result, 0)
            decision = read_reviews(path)[0]
            self.assertEqual(decision.decision, FindingStatus.CANNOT_DETERMINE)
            self.assertEqual(decision.evidence_quality, "incomplete")
            self.assertEqual(decision.seconds_spent, 83)


if __name__ == "__main__":
    unittest.main()
