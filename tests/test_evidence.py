import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eii.domain import (
    ContentBlock,
    CourseRelease,
    EvidenceBundle,
    EvidenceRef,
    Finding,
    FindingStatus,
    ModelRun,
    ReviewDecision,
    Severity,
    SourceLocator,
    UnitKind,
)
from eii.evidence import load_bundle, write_bundle


class EvidenceVerificationTests(unittest.TestCase):
    def bundle(self):
        locator = SourceLocator("fixture", "repo", "lesson", "a")
        block = ContentBlock("b", UnitKind.ACTIVITY, "Title", "Text", 0, locator)
        release = CourseRelease("r", "c", "en", "1", "Course", (block,), locator)
        run = ModelRun("local", "m", "p", {}, "input", "output", 1, 0.0)
        finding = Finding(
            "f",
            "gap",
            "Gap",
            "Explanation",
            Severity.HIGH,
            0.9,
            (EvidenceRef("r", "b", block.hash, "Text"),),
            ("en",),
            "Fix",
            model_run=run,
        )
        review = ReviewDecision(
            "f",
            FindingStatus.CONFIRMED,
            "reviewer",
            "yes",
            "2026-01-01T00:00:00+00:00",
            "sufficient",
            "high",
            5,
            "usable",
            10,
            "r1",
        )
        initial = EvidenceBundle.create((release,), (finding,))
        return replace(
            initial, reviews=(review,), model_runs=(run,), metadata={"release": "candidate"}
        )

    def test_round_trip_seals_late_reviews_and_model_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/evidence.json"
            original = self.bundle()
            self.assertNotEqual(
                original.id, EvidenceBundle.create(original.course_releases, original.findings).id
            )
            write_bundle(original, path)
            loaded = load_bundle(path)
            self.assertEqual(len(loaded.reviews), 1)
            self.assertEqual(len(loaded.model_runs), 1)
            self.assertNotEqual(loaded.id, original.id)

    def test_rejects_shape_reference_review_schema_and_id_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            write_bundle(self.bundle(), path)
            baseline = json.loads(path.read_text())
            mutations = []
            scalar = []
            mutations.append((scalar, "evidence bundle fields"))
            extra = dict(baseline)
            extra["extra"] = True
            mutations.append((extra, "evidence bundle fields"))
            bad_locator = json.loads(json.dumps(baseline))
            bad_locator["course_releases"][0]["source"] = []
            mutations.append((bad_locator, "locator fields"))
            bad_run = json.loads(json.dumps(baseline))
            bad_run["model_runs"][0] = {}
            mutations.append((bad_run, "model run fields"))
            bad_ref = json.loads(json.dumps(baseline))
            bad_ref["findings"][0]["evidence"][0]["block_hash"] = "sha256:" + "0" * 64
            mutations.append((bad_ref, "invalid evidence reference"))
            bad_excerpt = json.loads(json.dumps(baseline))
            bad_excerpt["findings"][0]["evidence"][0]["excerpt"] = "misquotation"
            mutations.append((bad_excerpt, "non-canonical evidence excerpt"))
            bad_review = json.loads(json.dumps(baseline))
            bad_review["reviews"][0]["finding_id"] = "unknown"
            mutations.append((bad_review, "unknown finding"))
            bad_schema = json.loads(json.dumps(baseline))
            bad_schema["schema_version"] = "9.0"
            mutations.append((bad_schema, "schema or canonical id"))
            bad_id = json.loads(json.dumps(baseline))
            bad_id["id"] = "sha256:" + "0" * 64
            mutations.append((bad_id, "schema or canonical id"))
            for document, message in mutations:
                with self.subTest(message=message):
                    path.write_text(json.dumps(document))
                    with self.assertRaisesRegex(ValueError, message):
                        load_bundle(path)


if __name__ == "__main__":
    unittest.main()
